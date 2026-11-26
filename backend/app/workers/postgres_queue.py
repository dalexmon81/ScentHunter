"""Transactional PostgreSQL queue with an optional safe legacy-backlog cutover."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, Text, Uuid, or_, select, text
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


def queue_min_created_at(environ=None) -> datetime | None:
    """Cut off legacy discovery/fetch work while keeping known-offer refreshes eligible."""
    env = os.environ if environ is None else environ
    raw = str(env.get("SCENTHUNTER_QUEUE_MIN_CREATED_AT") or "").strip()
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise RuntimeError(
            "SCENTHUNTER_QUEUE_MIN_CREATED_AT must be an ISO-8601 timestamp with timezone"
        ) from None
    if value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeError(
            "SCENTHUNTER_QUEUE_MIN_CREATED_AT must include a timezone"
        )
    return value.astimezone(timezone.utc)


def _require_postgresql() -> None:
    from sqlalchemy.engine import make_url
    if make_url(database_url()).get_backend_name() != "postgresql":
        raise RuntimeError("PostgreSQL ingestion queue requires the canonical PostgreSQL database")


def _serialize(payload: Mapping[str, Any]) -> tuple[dict, str]:
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a JSON object")
    raw = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return json.loads(raw), hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _daily_dedupe_key(payload_dedupe_key: str, schedule_key: str, day: str) -> str:
    """Give each scheduled day its own queue identity.

    A pre-cutover queued job may be intentionally ineligible for claiming. It
    must not deduplicate and block the next day's fresh discovery job forever.
    """
    material = "\0".join((schedule_key, day, payload_dedupe_key))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


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
    value, payload_dedupe = _serialize(payload)
    dedupe = _daily_dedupe_key(payload_dedupe, schedule_key, day)
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
            # The schedule row may already be marked for today even though its
            # old payload-only queue job is pre-cutover and cannot be claimed.
            # Continue to insert the day-scoped job; its dedupe key preserves
            # same-day idempotency without allowing the stale row to block it.
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
            conditions = [
                _jobs.c.status == "queued",
                _jobs.c.available_at <= _now(),
            ]
            minimum_created_at = queue_min_created_at()
            if minimum_created_at is not None:
                # Keep current-offer refreshes flowing across the cutover. The
                # legacy backlog consists of discovery/fetch work; refresh jobs
                # target already-known canonical offers and are safe to drain.
                conditions.append(or_(
                    _jobs.c.created_at >= minimum_created_at,
                    _jobs.c.stage == "refresh",
                ))
            row = conn.execute(select(_jobs).where(*conditions)
                .order_by(_jobs.c.available_at, _jobs.c.created_at, _jobs.c.id)
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


def fail_or_retry(
    job_id: str, attempts: int, error: str, *, retryable: bool = True,
    retry_after_seconds: int | None = None, cooldown_store_id: str | None = None,
) -> str:
    _require_postgresql()
    terminal = not retryable or attempts >= MAX_ATTEMPTS
    status = "failed" if terminal else "queued"
    now = _now()
    backoff_seconds = min(900, 2 ** attempts * 15)
    if retry_after_seconds is not None:
        try:
            backoff_seconds = max(backoff_seconds, min(3600, max(0, int(retry_after_seconds))))
        except (TypeError, ValueError):
            pass
    available = now if terminal else now + timedelta(seconds=backoff_seconds)
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
            # A retailer-wide Retry-After applies to its sibling discovery/fetch
            # jobs too. Keep the cooldown scoped to the same store ID.
            if not terminal and retry_after_seconds is not None and cooldown_store_id:
                conn.execute(text("""
                    UPDATE ingestion_queue_jobs
                    SET available_at = GREATEST(available_at, :available_at)
                    WHERE payload->>'store_id' = :store_id
                      AND stage IN ('discover', 'fetch')
                      AND status = 'queued'
                """), {"available_at": available, "store_id": str(cooldown_store_id)})
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
