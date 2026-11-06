"""Read-only aggregate operational metrics for the PostgreSQL catalog."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    CanonicalIdentityReview,
    IngestionDeadLetter,
    IngestionRaw,
    IngestionRun,
    Offer,
    Store,
)


def catalog_metrics_snapshot(session: Session, *, now: datetime | None = None) -> dict:
    """Return bounded aggregate health metrics; never returns raw retailer data."""
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    cutoff = reference - timedelta(hours=24)

    active_stores = session.scalar(
        select(func.count(Store.id)).where(Store.status == "active")
    ) or 0
    inactive_stores = session.scalar(
        select(func.count(Store.id)).where(Store.status != "active")
    ) or 0
    active_offers = session.scalar(
        select(func.count(Offer.id)).where(Offer.status == "active")
    ) or 0
    stale_offers = session.scalar(
        select(func.count(Offer.id)).where(
            Offer.status == "active",
            or_(Offer.captured_at < cutoff, Offer.valid_until < reference),
        )
    ) or 0
    pending_ingestion = session.scalar(
        select(func.count(IngestionRaw.id)).where(
            IngestionRaw.status.in_(("pending", "unmatched"))
        )
    ) or 0
    open_dead_letters = session.scalar(
        select(func.count(IngestionDeadLetter.id)).where(
            IngestionDeadLetter.status == "open"
        )
    ) or 0
    pending_identity_reviews = session.scalar(
        select(func.count(CanonicalIdentityReview.id)).where(
            CanonicalIdentityReview.status == "pending"
        )
    ) or 0

    store_rows = session.execute(
        select(
            Store.slug,
            Store.status,
            func.count(func.distinct(Offer.id)).label("active_offers"),
            func.max(IngestionRun.started_at).label("last_ingestion_started_at"),
        )
        .outerjoin(Offer, (Offer.store_id == Store.id) & (Offer.status == "active"))
        .outerjoin(IngestionRun, IngestionRun.store_id == Store.id)
        .group_by(Store.id, Store.slug, Store.status)
        .order_by(Store.slug.asc())
    ).all()

    return {
        "generated_at": reference.isoformat(),
        "read_only": True,
        "stores": {
            "active": int(active_stores),
            "inactive": int(inactive_stores),
            "by_store": [
                {
                    "slug": row.slug,
                    "status": row.status,
                    "active_offers": int(row.active_offers or 0),
                    "last_ingestion_started_at": (
                        row.last_ingestion_started_at.isoformat()
                        if row.last_ingestion_started_at else None
                    ),
                }
                for row in store_rows
            ],
        },
        "offers": {
            "active": int(active_offers),
            "stale_over_24h_or_expired": int(stale_offers),
        },
        "ingestion": {
            "pending_or_unmatched": int(pending_ingestion),
            "open_dead_letters": int(open_dead_letters),
        },
        "matching": {
            "pending_identity_reviews": int(pending_identity_reviews),
        },
    }
