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



def test_daily_discovery_recovers_when_today_is_scheduled_but_only_stale_job_exists(monkeypatch):
    import os
    import uuid
    from datetime import timedelta

    from sqlalchemy import (
        Column, DateTime, Integer, JSON, MetaData, String, Table, Text, Uuid,
        create_engine, insert, select, text,
    )
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.schema import Index

    from app.workers import postgres_queue as queue

    database_url = os.environ["SCENTHUNTER_TEST_POSTGRES_URL"]
    engine = create_engine(database_url)
    metadata = MetaData()
    jobs = Table(
        "test_daily_schedule_jobs", metadata,
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
    Index(
        "uq_test_daily_schedule_jobs_active_dedupe",
        jobs.c.stage, jobs.c.dedupe_key, unique=True,
        postgresql_where=text("status IN ('queued','running')"),
    )
    schedule = Table(
        "test_daily_schedule_state", metadata,
        Column("schedule_key", String(200), primary_key=True),
        Column("scheduled_day", String(10), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )
    metadata.create_all(engine)
    try:
        day = "2026-11-24"
        schedule_key = "schedule:deloox-be:daily-discovery"
        payload = {"store_id": "deloox-be-id", "cursor": None, "limit": 100}
        payload_dedupe = queue._serialize(payload)[1]
        stale_id = uuid.uuid4()
        now = datetime(2026, 11, 24, 9, 0, tzinfo=timezone.utc)
        with engine.begin() as connection:
            connection.execute(insert(schedule).values(
                schedule_key=schedule_key, scheduled_day=day, updated_at=now,
            ))
            connection.execute(insert(jobs).values(
                id=stale_id, stage="discover", payload=payload,
                dedupe_key=payload_dedupe, status="queued", attempts=0,
                max_attempts=5, available_at=now - timedelta(hours=1),
                created_at=now - timedelta(hours=1),
            ))

        monkeypatch.setattr(queue, "_schedule", schedule)
        monkeypatch.setattr(queue, "_jobs", jobs)
        monkeypatch.setattr(queue, "make_engine", lambda: engine)
        monkeypatch.setattr(queue, "_require_postgresql", lambda: None)

        first = queue.enqueue_daily_once(schedule_key, "discover", payload, day)
        second = queue.enqueue_daily_once(schedule_key, "discover", payload, day)

        assert first is not None and first != str(stale_id)
        assert second == first
        with engine.connect() as connection:
            rows = connection.execute(select(
                jobs.c.id, jobs.c.dedupe_key, jobs.c.status
            ).order_by(jobs.c.created_at)).all()
        assert len(rows) == 2, rows
        assert rows[0].id == stale_id and rows[0].status == "queued"
        assert rows[1].id == uuid.UUID(first) and rows[1].status == "queued"
        assert rows[1].dedupe_key == queue._daily_dedupe_key(
            payload_dedupe, schedule_key, day
        )
    finally:
        metadata.drop_all(engine)
        engine.dispose()
