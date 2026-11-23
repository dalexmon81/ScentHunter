"""Tests for resuming a deduplicated Notino discovery batch."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text

from scripts.bootstrap_notino_postgres import (
    _discovery_batch_started_at,
    _find_recent_discovery_job,
)


def _engine_with_job(created_at: datetime, status: str):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE ingestion_queue_jobs (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL
            )
        """))
        connection.execute(text("""
            INSERT INTO ingestion_queue_jobs (id, created_at, status)
            VALUES ('job-1', :created_at, :status)
        """), {"created_at": created_at.isoformat(), "status": status})
    return engine


def test_reuses_recent_running_discovery_batch():
    batch_started = datetime(2026, 11, 23, 7, 44, tzinfo=timezone.utc)
    bootstrap_started = batch_started + timedelta(minutes=5)
    engine = _engine_with_job(batch_started, "running")
    try:
        with engine.connect() as connection:
            actual = _discovery_batch_started_at(connection, "job-1", bootstrap_started)
        assert actual == batch_started
    finally:
        engine.dispose()


def test_rejects_stale_running_discovery_instead_of_duplicate_batch():
    batch_started = datetime(2026, 11, 23, 4, 0, tzinfo=timezone.utc)
    bootstrap_started = datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc)
    engine = _engine_with_job(batch_started, "running")
    try:
        with engine.connect() as connection:
            with pytest.raises(RuntimeError, match="refusing to enqueue a duplicate"):
                _discovery_batch_started_at(connection, "job-1", bootstrap_started)
    finally:
        engine.dispose()


def test_recent_completed_discovery_batch_can_be_adopted():
    batch_started = datetime(2026, 11, 23, 7, 40, tzinfo=timezone.utc)
    bootstrap_started = batch_started + timedelta(minutes=10)
    engine = _engine_with_job(batch_started, "completed")
    try:
        with engine.connect() as connection:
            actual = _discovery_batch_started_at(connection, "job-1", bootstrap_started)
        assert actual == batch_started
    finally:
        engine.dispose()


def test_missing_discovery_job_is_a_hard_error():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE ingestion_queue_jobs (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL
            )
        """))
    try:
        with engine.connect() as connection:
            with pytest.raises(RuntimeError, match="was not persisted"):
                _discovery_batch_started_at(
                    connection, "missing",
                    datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc),
                )
    finally:
        engine.dispose()



def test_adopts_oldest_recent_discovery_page_for_same_store():
    engine = create_engine("sqlite:///:memory:")
    now = datetime(2026, 11, 23, 8, 7, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE ingestion_queue_jobs (
                id TEXT PRIMARY KEY,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                payload TEXT NOT NULL
            )
        """))
        rows = [
            ("old", "queued", datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc),
             '{"store_id":"notino-fr","cursor":"0","limit":1000}'),
            ("first-page", "completed", datetime(2026, 11, 23, 7, 44, tzinfo=timezone.utc),
             '{"store_id":"notino-fr","cursor":null,"limit":1000}'),
            ("next-page", "queued", datetime(2026, 11, 23, 8, 3, tzinfo=timezone.utc),
             '{"store_id":"notino-fr","cursor":"1000","limit":1000}'),
            ("restart", "running", datetime(2026, 11, 23, 8, 6, tzinfo=timezone.utc),
             '{"store_id":"notino-fr","cursor":null,"limit":1000}'),
            ("other-store", "running", datetime(2026, 11, 23, 7, 45, tzinfo=timezone.utc),
             '{"store_id":"bplatz","cursor":null,"limit":1000}'),
        ]
        for row in rows:
            connection.execute(text("""
                INSERT INTO ingestion_queue_jobs (id,stage,status,created_at,payload)
                VALUES (:id,'discover',:status,:created_at,:payload)
            """), {
                "id": row[0], "status": row[1], "created_at": row[2], "payload": row[3],
            })
    try:
        with engine.connect() as connection:
            job_id = _find_recent_discovery_job(connection, "notino-fr", now)
        assert job_id == "first-page"
    finally:
        engine.dispose()


def test_does_not_adopt_discovery_job_older_than_two_hours():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE ingestion_queue_jobs (
                id TEXT PRIMARY KEY,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                payload TEXT NOT NULL
            )
        """))
        connection.execute(text("""
            INSERT INTO ingestion_queue_jobs (id,stage,status,created_at,payload)
            VALUES ('old','discover','queued',:created_at,'{"store_id":"notino-fr"}')
        """), {"created_at": datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc)})
    try:
        with engine.connect() as connection:
            job_id = _find_recent_discovery_job(
                connection, "notino-fr",
                datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc),
            )
        assert job_id is None
    finally:
        engine.dispose()
