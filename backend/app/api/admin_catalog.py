"""Read-only operational visibility for the PostgreSQL catalog.

All endpoints fail closed unless SCENTHUNTER_ADMIN_TOKEN is configured.
"""
from __future__ import annotations

import hmac
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import and_, func, or_, select

from app.db import make_session_factory
from app.models import (
    Brand,
    CanonicalIdentityReview,
    Fragrance,
    IngestionDeadLetter,
    IngestionRaw,
    IngestionRun,
    MatchAudit,
    Offer,
    ProductVariant,
    Store,
)

router = APIRouter(prefix="/catalog/admin", tags=["catalog-admin"])


def require_admin_token(
    supplied: str | None = Header(default=None, alias="X-ScentHunter-Admin-Token"),
):
    expected = os.environ.get("SCENTHUNTER_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="catalog_admin_disabled")
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid_admin_token")
    return True


def _count(session, model, *criteria):
    statement = select(func.count()).select_from(model)
    if criteria:
        statement = statement.where(*criteria)
    return int(session.scalar(statement) or 0)


def collect_catalog_metrics(session, *, now=None):
    """Build a bounded operational snapshot from persisted catalog tables."""
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(hours=24)

    active_offer = and_(
        Offer.status == "active",
        Offer.valid_until.is_not(None),
        Offer.valid_until > current,
    )
    stale_offer = and_(
        Offer.status == "active",
        or_(
            Offer.valid_until.is_(None),
            Offer.valid_until <= current,
            Offer.captured_at < cutoff,
        ),
    )
    missing_expiry_offer = and_(
        Offer.status == "active",
        Offer.valid_until.is_(None),
    )

    totals = {
        "brands": _count(session, Brand),
        "fragrances": _count(session, Fragrance),
        "variants": _count(session, ProductVariant),
        "active_stores": _count(session, Store, Store.status == "active"),
        "stores_missing_offer_ttl": _count(
            session, Store, Store.status == "active", Store.offer_ttl_minutes.is_(None)
        ),
        "active_offers": _count(session, Offer, active_offer),
        "stale_offers_24h": _count(session, Offer, stale_offer),
        "offers_missing_expiry": _count(session, Offer, missing_expiry_offer),
        "offers_without_canonical_variant": _count(
            session, Offer, Offer.status == "active", Offer.product_variant_id.is_(None)
        ),
        "offers_without_shipping_cost": _count(
            session, Offer, Offer.status == "active", Offer.shipping_cost.is_(None)
        ),
        "pending_raw_records": _count(session, IngestionRaw, IngestionRaw.status == "pending"),
        "unmatched_raw_records": _count(session, IngestionRaw, IngestionRaw.status == "unmatched"),
        "normalization_reviews_pending": _count(
            session,
            IngestionRaw,
            IngestionRaw.status == "unmatched",
            IngestionRaw.match_method == "normalization_review",
        ),
        "rejected_raw_records": _count(session, IngestionRaw, IngestionRaw.status == "rejected"),
        "pending_identity_reviews": _count(
            session, CanonicalIdentityReview, CanonicalIdentityReview.status == "pending"
        ),
        "pending_match_reviews": _count(
            session,
            MatchAudit,
            MatchAudit.reviewed_at.is_(None),
            or_(MatchAudit.confidence.is_(None), MatchAudit.confidence < 0.8),
        ),
        "open_dead_letters": _count(
            session, IngestionDeadLetter, IngestionDeadLetter.status == "open"
        ),
        "ingestion_runs_24h": _count(session, IngestionRun, IngestionRun.started_at >= cutoff),
        "failed_ingestion_runs_24h": _count(
            session, IngestionRun, IngestionRun.started_at >= cutoff,
            IngestionRun.status == "failed",
        ),
    }

    store_rows = session.execute(
        select(
            Store.slug,
            Store.name,
            Store.status,
            Store.last_successful_sync_at,
            func.count(Offer.id).filter(active_offer).label("active_offers"),
            func.count(Offer.id).filter(stale_offer).label("stale_offers_24h"),
        )
        .outerjoin(Offer, Offer.store_id == Store.id)
        .group_by(Store.id)
        .order_by(Store.slug.asc())
    ).all()

    stores = [
        {
            "slug": row.slug,
            "name": row.name,
            "status": row.status,
            "last_successful_sync_at": (
                row.last_successful_sync_at.isoformat()
                if row.last_successful_sync_at else None
            ),
            "active_offers": int(row.active_offers or 0),
            "stale_offers_24h": int(row.stale_offers_24h or 0),
        }
        for row in store_rows
    ]

    return {
        "generated_at": current.isoformat(),
        "window_hours": 24,
        "totals": totals,
        "stores": stores,
    }


@router.put("/stores/{store_slug}/freshness-policy")
def set_store_freshness_policy(
    store_slug: str,
    offer_ttl_minutes: int = Query(..., gt=0),
    _authorized: bool = Depends(require_admin_token),
):
    """Set the explicit maximum age for published offers from one store."""
    factory = make_session_factory()
    try:
        with factory() as session:
            store = session.scalar(select(Store).where(Store.slug == store_slug))
            if store is None:
                raise HTTPException(status_code=404, detail="catalog_store_not_found")
            store.offer_ttl_minutes = offer_ttl_minutes
            # Recompute existing active-offer expiry from each original source
            # observation so a policy change takes effect immediately.
            offers = session.scalars(select(Offer).where(
                Offer.store_id == store.id,
                Offer.status == "active",
            )).all()
            for offer in offers:
                offer.valid_until = offer.captured_at + timedelta(minutes=offer_ttl_minutes)
            session.commit()
            return {
                "store": store.slug,
                "offer_ttl_minutes": store.offer_ttl_minutes,
                "policy": "source_captured_at_plus_configured_ttl",
            }
    finally:
        factory.kw["bind"].dispose()


@router.get("/metrics")
def catalog_admin_metrics(_authorized: bool = Depends(require_admin_token)):
    factory = make_session_factory()
    try:
        with factory() as session:
            return collect_catalog_metrics(session)
    finally:
        factory.kw["bind"].dispose()


@router.get("/review-queue")
def catalog_admin_review_queue(
    limit: int = Query(default=50, ge=1, le=200),
    _authorized: bool = Depends(require_admin_token),
):
    factory = make_session_factory()
    try:
        with factory() as session:
            identity_rows = session.scalars(
                select(CanonicalIdentityReview)
                .where(CanonicalIdentityReview.status == "pending")
                .order_by(CanonicalIdentityReview.created_at.asc())
                .limit(limit)
            ).all()
            normalization_rows = session.execute(
                select(IngestionRaw, Store)
                .join(Store, Store.id == IngestionRaw.store_id)
                .where(
                    IngestionRaw.status == "unmatched",
                    IngestionRaw.match_method == "normalization_review",
                )
                .order_by(IngestionRaw.created_at.asc())
                .limit(limit)
            ).all()
            match_rows = session.execute(
                select(MatchAudit, Offer, Store)
                .join(Offer, Offer.id == MatchAudit.offer_id)
                .join(Store, Store.id == Offer.store_id)
                .where(
                    MatchAudit.reviewed_at.is_(None),
                    or_(MatchAudit.confidence.is_(None), MatchAudit.confidence < 0.8),
                )
                .order_by(MatchAudit.id.asc())
                .limit(limit)
            ).all()
            return {
                "identity_reviews": [
                    {
                        "id": str(row.id),
                        "canonical_key": row.canonical_key,
                        "reason": row.reason,
                        "source_reference": row.source_reference,
                        "created_at": row.created_at.isoformat(),
                        "normalized_payload": row.normalized_payload,
                    }
                    for row in identity_rows
                ],
                "normalization_reviews": [
                    {
                        "raw_id": str(raw.id),
                        "store": store.slug,
                        "external_product_id": raw.external_product_id,
                        "reason": raw.rejection_reason,
                        "raw_payload": raw.raw_payload,
                        "created_at": raw.created_at.isoformat(),
                    }
                    for raw, store in normalization_rows
                ],
                "match_reviews": [
                    {
                        "id": str(audit.id),
                        "offer_id": str(offer.id),
                        "store": store.slug,
                        "confidence": float(audit.confidence) if audit.confidence is not None else None,
                        "method": audit.method,
                        "reason": audit.reason,
                    }
                    for audit, offer, store in match_rows
                ],
            }
    finally:
        factory.kw["bind"].dispose()


@router.get("/dead-letters")
def catalog_admin_dead_letters(
    limit: int = Query(default=50, ge=1, le=200),
    _authorized: bool = Depends(require_admin_token),
):
    factory = make_session_factory()
    try:
        with factory() as session:
            rows = session.scalars(
                select(IngestionDeadLetter)
                .where(IngestionDeadLetter.status == "open")
                .order_by(IngestionDeadLetter.created_at.desc())
                .limit(limit)
            ).all()
            return {
                "count": len(rows),
                "items": [
                    {
                        "id": str(row.id),
                        "task_name": row.task_name,
                        "task_id": row.task_id,
                        "error": row.error,
                        "created_at": row.created_at.isoformat(),
                    }
                    for row in rows
                ],
            }
    finally:
        factory.kw["bind"].dispose()
