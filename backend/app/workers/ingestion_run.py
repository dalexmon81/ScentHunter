"""Durable lifecycle helpers for catalog connector ingestion runs.

The caller owns the SQLAlchemy transaction. These helpers never commit, enqueue
work, or perform network I/O, so workers can persist progress incrementally.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Final
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import IngestionRun, Store

_COUNTERS: Final = (
    "products_discovered",
    "offers_created",
    "offers_updated",
    "offers_rejected",
)
_TERMINAL_STATUSES: Final = {"completed", "partial", "failed"}


def start_ingestion_run(session: Session, *, store_id: UUID) -> UUID:
    """Create a running record only for an existing canonical store."""
    if session.get(Store, store_id) is None:
        raise ValueError("unknown store_id")
    row = IngestionRun(store_id=store_id, status="running", errors=[])
    session.add(row)
    session.flush()
    return row.id


def record_ingestion_progress(
    session: Session,
    *,
    run_id: UUID,
    products_discovered: int = 0,
    offers_created: int = 0,
    offers_updated: int = 0,
    offers_rejected: int = 0,
    error: str | None = None,
) -> None:
    """Atomically add non-negative counters and optionally retain one error."""
    increments = {
        "products_discovered": products_discovered,
        "offers_created": offers_created,
        "offers_updated": offers_updated,
        "offers_rejected": offers_rejected,
    }
    for name, value in increments.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} increment must be a non-negative integer")

    row = session.get(IngestionRun, run_id)
    if row is None:
        raise ValueError("unknown ingestion run")
    if row.status != "running":
        raise ValueError(f"cannot update ingestion run in status {row.status}")

    for name, value in increments.items():
        setattr(row, name, (getattr(row, name) or 0) + value)
    if error:
        errors = list(row.errors or [])
        errors.append(str(error)[:2000])
        row.errors = errors[-100:]
    session.flush()


def finish_ingestion_run(
    session: Session, *, run_id: UUID, status: str = "completed"
) -> None:
    """Close a running ingestion run exactly once."""
    if status not in _TERMINAL_STATUSES:
        raise ValueError(f"invalid terminal ingestion status: {status}")
    row = session.get(IngestionRun, run_id)
    if row is None:
        raise ValueError("unknown ingestion run")
    if row.status != "running":
        raise ValueError(f"cannot finish ingestion run in status {row.status}")
    row.status = status
    row.finished_at = datetime.now(timezone.utc)
    session.flush()
