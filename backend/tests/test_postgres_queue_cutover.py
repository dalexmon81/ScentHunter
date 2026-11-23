"""Regression tests for the bounded PostgreSQL queue cutover."""

from datetime import datetime, timezone

import pytest

from app.workers.postgres_queue import queue_min_created_at


def test_queue_cutover_is_disabled_when_unconfigured():
    assert queue_min_created_at({}) is None


def test_queue_cutover_parses_utc_z_timestamp():
    assert queue_min_created_at({
        "SCENTHUNTER_QUEUE_MIN_CREATED_AT": "2026-11-23T07:00:00Z",
    }) == datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc)


def test_queue_cutover_normalizes_explicit_timezone():
    assert queue_min_created_at({
        "SCENTHUNTER_QUEUE_MIN_CREATED_AT": "2026-11-23T08:00:00+01:00",
    }) == datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc)


def test_queue_cutover_rejects_timezone_naive_timestamp():
    with pytest.raises(RuntimeError, match="must include a timezone"):
        queue_min_created_at({
            "SCENTHUNTER_QUEUE_MIN_CREATED_AT": "2026-11-23T07:00:00",
        })


def test_queue_cutover_rejects_invalid_timestamp():
    with pytest.raises(RuntimeError, match="ISO-8601 timestamp"):
        queue_min_created_at({
            "SCENTHUNTER_QUEUE_MIN_CREATED_AT": "not-a-date",
        })


def test_claim_next_skips_legacy_fetch_but_allows_existing_offer_refresh(monkeypatch):
    import uuid
    from datetime import timedelta

    from sqlalchemy import (
        Column, DateTime, Integer, JSON, MetaData, String, Table, Text, Uuid,
        create_engine, insert, select,
    )

    from app.workers import postgres_queue as queue

    database_url = __import__("os").environ["SCENTHUNTER_TEST_POSTGRES_URL"]
    engine = create_engine(database_url)
    metadata = MetaData()
    jobs = Table(
        "test_queue_cutover_jobs", metadata,
        Column("id", Uuid(as_uuid=True), primary_key=True),
        Column("stage", String(24), nullable=False),
        Column("payload", JSON, nullable=False),
        Column("dedupe_key", String(64), nullable=False),
        Column("status", String(16), nullable=False),
        Column("attempts", Integer, nullable=False),
        Column("max_attempts", Integer, nullable=False),
        Column("available_at", DateTime(timezone=True), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("started_at", DateTime(timezone=True)),
        Column("finished_at", DateTime(timezone=True)),
        Column("worker_id", String(200)),
        Column("last_error", Text),
    )
    metadata.create_all(engine)
    try:
        now = datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)
        old_id, old_refresh_id, new_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        with engine.begin() as connection:
            connection.execute(insert(jobs), [
                {
                    "id": old_id, "stage": "fetch", "payload": {"store_id": "legacy"},
                    "dedupe_key": "old", "status": "queued", "attempts": 0,
                    "max_attempts": 5, "available_at": now - timedelta(days=1),
                    "created_at": now - timedelta(days=1),
                },
                {
                    "id": old_refresh_id, "stage": "refresh", "payload": {"store_id": "bplatz"},
                    "dedupe_key": "old-refresh", "status": "queued", "attempts": 0,
                    "max_attempts": 5, "available_at": now - timedelta(days=1),
                    "created_at": now - timedelta(days=1),
                },
                {
                    "id": new_id, "stage": "discover", "payload": {"store_id": "notino-fr"},
                    "dedupe_key": "new", "status": "queued", "attempts": 0,
                    "max_attempts": 5, "available_at": now - timedelta(days=1),
                    "created_at": now,
                },
            ])

        monkeypatch.setenv("SCENTHUNTER_QUEUE_MIN_CREATED_AT", "2026-11-23T07:00:00Z")
        monkeypatch.setattr(queue, "_jobs", jobs)
        monkeypatch.setattr(queue, "make_engine", lambda: engine)
        claimed = queue.claim_next("cutover-test-worker")
        assert claimed is not None
        assert claimed["id"] == old_refresh_id

        with engine.connect() as connection:
            statuses = dict(connection.execute(
                select(jobs.c.id, jobs.c.status)
            ).all())
        assert statuses[old_id] == "queued"
        assert statuses[old_refresh_id] == "running"
        assert statuses[new_id] == "queued"
    finally:
        metadata.drop_all(engine)
        engine.dispose()
