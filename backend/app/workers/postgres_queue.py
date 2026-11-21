"""Transactional PostgreSQL queue for canonical catalog ingestion.

Jobs live in the canonical catalog database. Claims use FOR UPDATE SKIP LOCKED,
so multiple worker processes can safely compete without a Redis dependency.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.db import make_engine, database_url

MAX_ATTEMPTS = 5
STALE_AFTER_SECONDS = 900
_ALLOWED_STAGES = {"discover", "fetch", "refresh"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _table():
    from sqlalchemy import MetaData, Table
    metadata = MetaData()
    return Table("ingestion_queue_jobs", metadata, autoload_with=make_engine())


def _payload_json(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a JSON object")
    return json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _dedupe_key(payload_json: str) -> str:
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


def _require_postgresql() -> None:
    from sqlalchemy.engine import make_url
    if make_url(database_url()).get_backend_name() != "postgresql":
        raise RuntimeError("PostgreSQL ingestion queue requires the canonical PostgreSQL database")


def enqueue(stage: str, payload: Mapping[str, Any]) -> str:
    if stage not in _ALLOWED_STAGES:
        raise ValueError(f"unsupported ingestion stage: {stage}")
    _require_postgresql()
    payload_json = _payload_json(payload)
    payload_value = json.loads(payload_json)
    dedupe = _dedupe_key(payload_json)
    table = _table()
    job_id = uuid.uuid4()
    engine = make_engine()
    try:
        with engine.begin() as conn:
            statement = pg_insert(table).values(
                id=job_id, stage=stage, payload=payload_value, dedupe_key=dedupe,
                status="queued", attempts=0, max_attempts=MAX_ATTEMPTS,
                available_at=_now(), created_at=_now(),
            ).on_conflict_do_nothing(
                index_elements=[table.c.stage, table.c.dedupe_key],
                index_where=text("status IN ('queued','running')"),
            ).returning(table.c.id)
            inserted = conn.execute(statement).scalar_one_or_none()
            if inserted is not None:
                return str(inserted)
            existing = conn.execute(
                select(table.c.id).where(
                    table.c.stage == stage, table.c.dedupe_key == dedupe,
                    table.c.status.in_(("queued", "running")),
                ).order_by(table.c.created_at).limit(1)
            ).scalar_one_or_none()
            if existing is None:
                raise RuntimeError("queue deduplication conflict could not be resolved")
            return str(existing)
    finally:
        engine.dispose()


def enqueue_daily_once(schedule_key: str, stage: str, payload: Mapping[str, Any], day: str) -> str | None:
    # The schedule key is included in the durable payload so the normal active-job
    # dedupe index also makes concurrent schedulers idempotent for a given UTC day.
    return enqueue(stage, {**dict(payload), "_schedule_key": schedule_key, "_schedule_day": day})


def claim_next(worker_id: str) -> dict[str, Any] | None:
    _require_postgresql()
    table = _table()
    engine = make_engine()
    try:
        with engine.begin() as conn:
            row = conn.execute(
                select(table).where(
                    table.c.status == "queued", table.c.available_at <= _now()
                ).order_by(table.c.available_at, table.c.created_at, table.c.id)
                .with_for_update(skip_locked=True).limit(1)
            ).mappings().first()
            if row is None:
                return None
            now = _now()
            conn.execute(
                table.update().where(table.c.id == row["id"]).values(
                    status="running", attempts=table.c.attempts + 1,
                    started_at=now, finished_at=None, worker_id=worker_id, last_error=None,
                )
            )
            result = dict(row)
            result.update(status="running", attempts=int(row["attempts"]) + 1,
                          started_at=now, worker_id=worker_id)
            return result
    finally:
        engine.dispose()


def finish(job_id: str) -> None:
    _require_postgresql()
    table = _table()
    engine = make_engine()
    try:
        with engine.begin() as conn:
            result = conn.execute(table.update().where(
                table.c.id == uuid.UUID(str(job_id)), table.c.status == "running"
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
    table = _table()
    engine = make_engine()
    try:
        with engine.begin() as conn:
            result = conn.execute(table.update().where(
                table.c.id == uuid.UUID(str(job_id)), table.c.status == "running"
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
    cutoff = _now() - timedelta(seconds=STALE_AFTER_SECONDS)
    now = _now()
    table = _table()
    engine = make_engine()
    try:
        with engine.begin() as conn:
            result = conn.execute(table.update().where(
                table.c.status == "running", table.c.started_at < cutoff
            ).values(
                status=table.c.status,  # replaced below with SQL CASE for attempt cap
                available_at=now, finished_at=None, worker_id=None,
                last_error="worker heartbeat expired; job returned to queue",
            ))
            # Apply terminal status separately; SQL expression keeps the transition atomic.
            conn.execute(text("""
                UPDATE ingestion_queue_jobs
                SET status = CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'queued' END,
                    finished_at = CASE WHEN attempts >= max_attempts THEN :now ELSE NULL END
                WHERE status = 'running' AND started_at < :cutoff
            """), {"now": now, "cutoff": cutoff})
            return int(result.rowcount or 0)
    finally:
        engine.dispose()
