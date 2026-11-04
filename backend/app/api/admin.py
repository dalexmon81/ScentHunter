"""Read-only, authenticated operational views for catalog administration."""
from __future__ import annotations
import hmac
import os
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from app.db import make_session_factory
from app.models import CanonicalIdentityReview, IngestionRun, Store

router = APIRouter(prefix="/api/admin", tags=["catalog-admin"])


def _authorize(authorization: str = Header(default="")) -> None:
    expected = os.environ.get("SCENTHUNTER_ADMIN_TOKEN", "")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="admin_api_not_configured")
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="admin_unauthorized")


@router.get("/connectors")
def connector_status(_auth: None = Depends(_authorize)):
    """Return connector/store health metadata; never starts a connector."""
    factory = make_session_factory()
    try:
        with factory() as session:
            stores = session.scalars(select(Store).order_by(Store.name)).all()
            return {"count": len(stores), "connectors": [{
                "store_id": str(s.id), "name": s.name, "slug": s.slug,
                "status": s.status, "country": s.country, "currency": s.currency,
                "reliability_score": str(s.reliability_score) if s.reliability_score is not None else None,
                "last_successful_sync_at": s.last_successful_sync_at,
                "temporarily_unavailable": s.status != "active",
            } for s in stores]}
    finally:
        factory.kw["bind"].dispose()


@router.get("/ingestion")
def ingestion_runs(limit: int = Query(50, ge=1, le=200), _auth: None = Depends(_authorize)):
    """Return recent durable ingestion runs."""
    factory = make_session_factory()
    try:
        with factory() as session:
            rows = session.scalars(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit)).all()
            return {"count": len(rows), "runs": [{
                "id": str(x.id), "store_id": str(x.store_id), "status": x.status,
                "started_at": x.started_at, "finished_at": x.finished_at,
                "products_discovered": x.products_discovered, "offers_created": x.offers_created,
                "offers_updated": x.offers_updated, "offers_rejected": x.offers_rejected,
                "errors": x.errors or [],
            } for x in rows]}
    finally:
        factory.kw["bind"].dispose()


@router.get("/matching")
def matching_reviews(status: str = "pending", limit: int = Query(50, ge=1, le=200), _auth: None = Depends(_authorize)):
    """Return canonical identity review queue without changing review state."""
    factory = make_session_factory()
    try:
        with factory() as session:
            stmt = select(CanonicalIdentityReview).order_by(CanonicalIdentityReview.created_at.asc()).limit(limit)
            if status != "all":
                stmt = stmt.where(CanonicalIdentityReview.status == status)
            rows = session.scalars(stmt).all()
            return {"count": len(rows), "reviews": [{
                "id": str(x.id), "canonical_key": x.canonical_key, "reason": x.reason,
                "status": x.status, "created_at": x.created_at,
                "normalized_payload": x.normalized_payload,
            } for x in rows]}
    finally:
        factory.kw["bind"].dispose()
