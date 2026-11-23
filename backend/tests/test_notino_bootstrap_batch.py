"""Tests for resuming a deduplicated Notino discovery batch."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text

from scripts.bootstrap_notino_postgres import _discovery_batch_started_at


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
    batch_started = datetime(2026, 11, 23, 6, 0, tzinfo=timezone.utc)
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
