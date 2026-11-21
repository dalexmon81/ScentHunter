"""Transactional PostgreSQL queue for canonical catalog ingestion."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, Text, Uuid, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import database_url, make_engine

MAX_ATTEMPTS = 5
STALE_AFTER_SECONDS = 900
_ALLOWED_STAGES = {"discover", "fetch", "refresh"}
_metadata = MetaData()
_jobs = Table(
    "ingestion_queue_jobs", _metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("stage", String(24), nullable=False), Column("payload", JSON, nullable=False),
    Column("dedupe_key", String(64), nullable=False), Column("status", String(16), nullable=False),
    Column("attempts", Integer, nullable=False), Column("max_attempts", Integer, nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True)), Column("finished_at", DateTime(timezone=True)),
    Column("worker_id", String(200)), Column("last_error", Text),
)
_schedule = Table(
    "ingestion_queue_schedule", _metadata,
    Column("schedule_key", String(200), primary_key=True),
    Column("scheduled_day", String(10), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_postgresql() -> None:
    from sqlalchemy.engine import make_url
    if make_url(database_url()).get_backend_name() != "postgresql":
        raise RuntimeError("PostgreSQL ingestion queue requires the canonical PostgreSQL database")


def _serialize(payload: Mapping[str, Any]) -> tuple[dict, str]:
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a JSON object")
    raw = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return json.loads(raw), hashlib.sha256(raw.encode("utf-8")).hexdigest()


def enqueue(stage: str, payload: Mapping[str, Any]) -> str:
    if stage not in _ALLOWED_STAGES:
        raise ValueError(f"unsupported ingestion stage: {stage}")
    _require_postgresql()
    value, dedupe = _serialize(payload)
    engine = make_engine()
    try:
        with engine.begin() as conn:
            inserted = conn.execute(
                pg_insert(_jobs).values(
                    id=uuid.uuid4(), stage=stage, payload=value, dedupe_key=dedupe,
                    status="queued", attempts=0, max_attempts=MAX_ATTEMPTS,
                    available_at=_now(), created_at=_now(),
                ).on_conflict_do_nothing(
                    index_elements=[_jobs.c.stage, _jobs.c.dedupe_key],
                    index_where=text("status IN ('queued','running')"),
                ).returning(_jobs.c.id)
            ).scalar_one_or_none()
            if inserted is not None:
                return str(inserted)
            existing = conn.execute(select(_jobs.c.id).where(
                _jobs.c.stage == stage, _jobs.c.dedupe_key == dedupe,
                _jobs.c.status.in_(("queued", "running")),
            ).order_by(_jobs.c.created_at).limit(1)).scalar_one_or_none()
            if existing is None:
                raise RuntimeError("queue deduplication conflict could not be resolved")
            return str(existing)
    finally:
        engine.dispose()


def enqueue_daily_once(schedule_key: str, stage: str, payload: Mapping[str, Any], day: str) -> str | None:
    if stage not in _ALLOWED_STAGES:
        raise ValueError(f"unsupported ingestion stage: {stage}")
    _require_postgresql()
    value, dedupe = _serialize(payload)
    engine = make_engine()
    try:
        with engine.begin() as conn:
            scheduled = conn.execute(pg_insert(_schedule).values(
                schedule_key=schedule_key, scheduled_day=day, updated_at=_now()
            ).on_conflict_do_update(
                index_elements=[_schedule.c.schedule_key],
                set_={"scheduled_day": day, "updated_at": _now()},
                where=_schedule.c.scheduled_day != day,
            ).returning(_schedule.c.schedule_key)).scalar_one_or_none()
            if scheduled is None:
                return None
            job_id = uuid.uuid4()
            inserted = conn.execute(pg_insert(_jobs).values(
                id=job_id, stage=stage, payload=value, dedupe_key=dedupe,
                status="queued", attempts=0, max_attempts=MAX_ATTEMPTS,
                available_at=_now(), created_at=_now(),
            ).on_conflict_do_nothing(
                index_elements=[_jobs.c.stage, _jobs.c.dedupe_key],
                index_where=text("status IN ('queued','running')"),
            ).returning(_jobs.c.id)).scalar_one_or_none()
            if inserted is not None:
                return str(inserted)
            existing = conn.execute(select(_jobs.c.id).where(
                _jobs.c.stage == stage, _jobs.c.dedupe_key == dedupe,
                _jobs.c.status.in_(("queued", "running")),
            ).order_by(_jobs.c.created_at).limit(1)).scalar_one_or_none()
            return str(existing) if existing is not None else None
    finally:
        engine.dispose()


def claim_next(worker_id: str) -> dict[str, Any] | None:
    _require_postgresql()
    engine = make_engine()
    try:
        with engine.begin() as conn:
            row = conn.execute(select(_jobs).where(
                _jobs.c.status == "queued", _jobs.c.available_at <= _now()
            ).order_by(_jobs.c.available_at, _jobs.c.created_at, _jobs.c.id)
             .with_for_update(skip_locked=True).limit(1)).mappings().first()
            if row is None:
                return None
            now = _now()
            conn.execute(_jobs.update().where(_jobs.c.id == row["id"]).values(
                status="running", attempts=_jobs.c.attempts + 1,
                started_at=now, finished_at=None, worker_id=worker_id, last_error=None,
            ))
            result = dict(row)
            result.update(status="running", attempts=int(row["attempts"]) + 1,
                          started_at=now, worker_id=worker_id)
            return result
    finally:
        engine.dispose()


def finish(job_id: str) -> None:
    _require_postgresql()
    engine = make_engine()
    try:
        with engine.begin() as conn:
            result = conn.execute(_jobs.update().where(
                _jobs.c.id == uuid.UUID(str(job_id)), _jobs.c.status == "running"
            ).values(status="completed", finished_at=_now(), worker_id=None))
            if result.rowcount != 1:
                raise RuntimeError("job is not currently running")
    finally:
        engine.dispose()


def fail_or_retry(job_id: str, attempts: int, error: str, *, retryable: bool = True) -> str:
    _require_postgresql()
    terminal = not retryable or attempts >= MAX_ATTEMPTS
    status = "failed" if terminal else "queued"
    now = _now()
    available = now if terminal else now + timedelta(seconds=min(900, 2 ** attempts * 15))
    engine = make_engine()
    try:
        with engine.begin() as conn:
            result = conn.execute(_jobs.update().where(
                _jobs.c.id == uuid.UUID(str(job_id)), _jobs.c.status == "running"
            ).values(status=status, available_at=available,
                     finished_at=now if terminal else None, worker_id=None,
                     last_error=str(error)[:4000]))
            if result.rowcount != 1:
                raise RuntimeError("job is not currently running")
        return status
    finally:
        engine.dispose()


def recover_stale() -> int:
    _require_postgresql()
    now = _now()
    cutoff = now - timedelta(seconds=STALE_AFTER_SECONDS)
    engine = make_engine()
    try:
        with engine.begin() as conn:
            result = conn.execute(text("""
                UPDATE ingestion_queue_jobs
                SET status = CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'queued' END,
                    available_at = :now,
                    finished_at = CASE WHEN attempts >= max_attempts THEN :now ELSE NULL END,
                    worker_id = NULL,
                    last_error = 'worker heartbeat expired; job returned to queue'
                WHERE status = 'running' AND started_at < :cutoff
            """), {"now": now, "cutoff": cutoff})
            return int(result.rowcount or 0)
    finally:
        engine.dispose()
