"""Track connector health and quarantine repeatedly unavailable stores."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Store

DEFAULT_QUARANTINE_THRESHOLD = 5


def record_connector_failure(
    session: Session, *, store_id: UUID, error: str,
    threshold: int = DEFAULT_QUARANTINE_THRESHOLD,
) -> bool:
    """Record one connector-wide failure; return True if store is quarantined."""
    if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 1:
        raise ValueError("threshold must be a positive integer")
    store = session.scalar(select(Store).where(Store.id == store_id).with_for_update())
    if store is None:
        raise ValueError("unknown store_id")
    if store.status == "quarantined":
        return True
    if store.status != "active":
        return False

    store.consecutive_failures = (store.consecutive_failures or 0) + 1
    store.last_connector_error = str(error)[:2000]
    if store.consecutive_failures >= threshold:
        store.status = "quarantined"
        store.quarantined_at = datetime.now(timezone.utc)
    session.flush()
    return store.status == "quarantined"


def record_connector_success(session: Session, *, store_id: UUID) -> bool:
    """Reset the failure streak only for an active store; never auto-unquarantine."""
    store = session.scalar(select(Store).where(Store.id == store_id).with_for_update())
    if store is None:
        raise ValueError("unknown store_id")
    if store.status != "active":
        return False
    store.consecutive_failures = 0
    store.last_connector_error = None
    store.last_successful_sync_at = datetime.now(timezone.utc)
    session.flush()
    return True



def reinstate_connector(
    session: Session, *, store_id: UUID, confirmed: bool,
) -> bool:
    """Explicit operator recovery; never invoke from a scheduled worker."""
    if confirmed is not True:
        raise ValueError("explicit confirmation is required to reinstate a connector")
    store = session.scalar(select(Store).where(Store.id == store_id).with_for_update())
    if store is None:
        raise ValueError("unknown store_id")
    if store.status != "quarantined":
        return False
    store.status = "active"
    store.consecutive_failures = 0
    store.last_connector_error = None
    store.quarantined_at = None
    session.flush()
    return True
