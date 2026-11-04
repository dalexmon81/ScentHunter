"""Authenticated, read-only operational metrics and guarded admin actions."""
from __future__ import annotations

import hmac
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select

from app.db import make_session_factory
from app.models import (
    CanonicalIdentityReview, IngestionRaw, IngestionRun, MatchAudit,
    Offer, Store,
)
from app.schemas.catalog import AdminConnectorList, AdminIngestionRunList, AdminMatchingReviewList
from app.services.observability import search_latency_snapshot

router = APIRouter(prefix="/api/admin", tags=["catalog-admin"])


def _authorize(authorization: str = Header(default="")) -> None:
    expected = os.environ.get("SCENTHUNTER_ADMIN_TOKEN", "")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="admin_api_not_configured")
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="admin_unauthorized")


def _session_factory():
    return make_session_factory()


@router.get("/connectors", response_model=AdminConnectorList)
def connector_status(_auth: None = Depends(_authorize)):
    """Return connector/store health metadata; never starts a connector."""
    factory = _session_factory()
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


@router.get("/ingestion", response_model=AdminIngestionRunList)
def ingestion_runs(limit: int = Query(50, ge=1, le=200), _auth: None = Depends(_authorize)):
    """Return recent durable ingestion runs."""
    factory = _session_factory()
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


@router.get("/matching", response_model=AdminMatchingReviewList)
def matching_reviews(status: str = "pending", limit: int = Query(50, ge=1, le=200), _auth: None = Depends(_authorize)):
    """Return canonical identity review queue without changing review state."""
    factory = _session_factory()
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


@router.get("/metrics")
def operational_metrics(_auth: None = Depends(_authorize)):
    """Return persisted catalog, matching, ingestion and freshness metrics."""
    factory = _session_factory()
    now = datetime.now(timezone.utc)
    try:
        with factory() as session:
            total_offers = session.scalar(select(func.count()).select_from(Offer)) or 0
            published = session.scalar(select(func.count()).select_from(Offer).where(
                Offer.publication_status == "published"
            )) or 0
            rejected_offers = session.scalar(select(func.count()).select_from(Offer).where(
                Offer.publication_status == "rejected"
            )) or 0
            rejected = session.scalar(select(func.count()).select_from(IngestionRaw).where(
                IngestionRaw.status == "rejected"
            )) or 0
            per_store = session.execute(
                select(Store.slug, Store.name, func.count(Offer.id))
                .outerjoin(Offer, Offer.store_id == Store.id)
                .group_by(Store.id, Store.slug, Store.name)
                .order_by(Store.name)
            ).all()

            audits = session.scalars(select(MatchAudit)).all()
            auto_matches = sum(
                1 for item in audits
                if item.reviewed_at is None and item.confidence is not None and float(item.confidence) >= 0.95
            )
            ambiguous_matches = sum(
                1 for item in audits
                if item.confidence is None or float(item.confidence) < 0.95
            )
            audit_count = len(audits)

            active_offers = session.scalars(select(Offer).where(Offer.status == "active")).all()
            ages_hours = []
            stock_valid = 0
            valid_stock_values = {"in_stock", "out_of_stock", "preorder", "backorder"}
            for offer in active_offers:
                captured = offer.captured_at
                if captured is not None:
                    if captured.tzinfo is None:
                        captured = captured.replace(tzinfo=timezone.utc)
                    ages_hours.append(max(0.0, (now - captured).total_seconds() / 3600))
                if str(offer.availability or "").strip().casefold() in valid_stock_values:
                    stock_valid += 1

            runs_24h = session.scalars(select(IngestionRun).where(
                IngestionRun.started_at >= now - timedelta(hours=24)
            )).all()
            failed_runs = sum(1 for run in runs_24h if run.status == "failed")
            quarantined = session.scalar(select(func.count()).select_from(Store).where(
                Store.status == "quarantined"
            )) or 0

            return {
                "generated_at": now.isoformat(),
                "offers": {
                    "total": int(total_offers),
                    "published": int(published),
                    "rejected": int(rejected_offers),
                    "rejected_raw_records": int(rejected),
                    "by_store": [
                        {"store": slug, "name": name, "offers": int(count)}
                        for slug, name, count in per_store
                    ],
                },
                "matching": {
                    "audited_matches": audit_count,
                    "automatic_count": auto_matches,
                    "automatic_rate": round(auto_matches / audit_count, 4) if audit_count else None,
                    "ambiguous_count": ambiguous_matches,
                    "ambiguous_rate": round(ambiguous_matches / audit_count, 4) if audit_count else None,
                    "confidence_threshold": 0.95,
                },
                "search_latency": search_latency_snapshot(),
                "connectors": {
                    "runs_last_24h": len(runs_24h),
                    "failed_runs_last_24h": failed_runs,
                    "error_rate_last_24h": round(failed_runs / len(runs_24h), 4) if runs_24h else None,
                    "quarantined_stores": int(quarantined),
                },
                "price_freshness": {
                    "active_offers_with_timestamp": len(ages_hours),
                    "average_age_hours": round(sum(ages_hours) / len(ages_hours), 2) if ages_hours else None,
                    "offers_with_valid_stock": stock_valid,
                    "valid_stock_rate": round(stock_valid / len(active_offers), 4) if active_offers else None,
                },
            }
    finally:
        factory.kw["bind"].dispose()


@router.get("/alerts")
def operational_alerts(
    stale_after_hours: int = Query(48, ge=1, le=720),
    error_rate_threshold: float = Query(0.25, ge=0.01, le=1),
    ambiguous_rate_threshold: float = Query(0.20, ge=0.01, le=1),
    _auth: None = Depends(_authorize),
):
    """Evaluate actionable connector, offer-freshness and matching alerts."""
    factory = _session_factory()
    now = datetime.now(timezone.utc)
    alerts = []
    try:
        with factory() as session:
            stores = session.scalars(select(Store).order_by(Store.name)).all()
            for store in stores:
                recent = session.scalars(select(IngestionRun).where(
                    IngestionRun.store_id == store.id
                ).order_by(IngestionRun.started_at.desc()).limit(8)).all()
                if recent and recent[0].status == "completed" and (recent[0].products_discovered or 0) == 0:
                    previous_positive = any((run.products_discovered or 0) > 0 for run in recent[1:])
                    if previous_positive:
                        alerts.append({
                            "severity": "warning", "code": "connector_zero_discovery",
                            "store": store.slug, "message": f"{store.name}: ultimo sync completato senza prodotti, dopo sync precedenti positivi.",
                        })
                if store.status == "quarantined":
                    alerts.append({
                        "severity": "critical", "code": "store_quarantined",
                        "store": store.slug, "message": f"{store.name}: connector in quarantena.",
                    })

            window_runs = session.scalars(select(IngestionRun).where(
                IngestionRun.started_at >= now - timedelta(hours=24)
            )).all()
            failed = sum(1 for run in window_runs if run.status == "failed")
            error_rate = failed / len(window_runs) if window_runs else 0.0
            if len(window_runs) >= 4 and error_rate >= error_rate_threshold:
                alerts.append({
                    "severity": "critical", "code": "connector_error_rate_high",
                    "rate": round(error_rate, 4), "sample_size": len(window_runs),
                    "message": f"Tasso di errori connector nelle ultime 24 ore: {error_rate:.0%}.",
                })

            stale_cutoff = now - timedelta(hours=stale_after_hours)
            stale_count = session.scalar(select(func.count()).select_from(Offer).where(
                Offer.status == "active",
                Offer.publication_status == "published",
                Offer.captured_at < stale_cutoff,
            )) or 0
            if stale_count:
                alerts.append({
                    "severity": "warning", "code": "published_prices_stale",
                    "count": int(stale_count), "threshold_hours": stale_after_hours,
                    "message": f"{stale_count} offerte pubblicate non aggiornate da oltre {stale_after_hours} ore.",
                })

            match_window_start = now - timedelta(days=8)
            recent_raw = session.scalars(select(IngestionRaw).where(
                IngestionRaw.updated_at >= match_window_start,
                IngestionRaw.status.in_(("unmatched", "matched")),
            )).all()
            current_ambiguous = sum(
                1 for row in recent_raw
                if row.updated_at >= now - timedelta(hours=24)
                and (row.status == "unmatched" or row.match_confidence is None or float(row.match_confidence) < 0.95)
            )
            previous_ambiguous = sum(
                1 for row in recent_raw
                if row.updated_at < now - timedelta(hours=24)
                and (row.status == "unmatched" or row.match_confidence is None or float(row.match_confidence) < 0.95)
            )
            previous_daily_average = previous_ambiguous / 7
            if previous_daily_average >= 1 and current_ambiguous > previous_daily_average * 1.5:
                alerts.append({
                    "severity": "warning", "code": "ambiguous_matching_rate_rising",
                    "current_24h": current_ambiguous,
                    "previous_daily_average": round(previous_daily_average, 1),
                    "message": "I match ambigui nelle ultime 24 ore sono aumentati di oltre il 50% rispetto alla media giornaliera dei 7 giorni precedenti.",
                })

            # Compare each store's latest 24h published count with the preceding
            # 7-day daily average. Require a meaningful baseline before alerting.
            current_start = now - timedelta(hours=24)
            previous_start = now - timedelta(days=8)
            for store in stores:
                current_count = session.scalar(select(func.count()).select_from(Offer).where(
                    Offer.store_id == store.id, Offer.publication_status == "published",
                    Offer.captured_at >= current_start,
                )) or 0
                previous_count = session.scalar(select(func.count()).select_from(Offer).where(
                    Offer.store_id == store.id, Offer.publication_status == "published",
                    Offer.captured_at >= previous_start, Offer.captured_at < current_start,
                )) or 0
                daily_baseline = previous_count / 7
                if daily_baseline >= 3 and current_count < daily_baseline * 0.5:
                    alerts.append({
                        "severity": "warning", "code": "store_offer_volume_drop",
                        "store": store.slug, "current_24h": int(current_count),
                        "baseline_24h": round(daily_baseline, 1),
                        "message": f"{store.name}: volume offerte nelle ultime 24 ore in calo di oltre il 50%.",
                    })
            return {"generated_at": now.isoformat(), "count": len(alerts), "alerts": alerts}
    finally:
        factory.kw["bind"].dispose()


@router.post("/connectors/{store_key}/restart", status_code=202)
def restart_connector(store_key: str, _auth: None = Depends(_authorize)):
    """Queue a fresh discovery run for an active store; never unquarantines it."""
    factory = _session_factory()
    try:
        with factory() as session:
            store = session.scalar(select(Store).where(Store.slug == store_key))
            if store is None:
                raise HTTPException(status_code=404, detail="store_not_found")
            if store.status != "active":
                raise HTTPException(status_code=409, detail="store_must_be_active_before_restart")
    finally:
        factory.kw["bind"].dispose()
    try:
        from app.workers.ingestion_tasks import discover_store_products
        job = discover_store_products.apply_async(args=[store_key], queue="discovery")
        return {"status": "queued", "store": store_key, "job_id": str(job.id)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="connector_queue_unavailable") from exc


@router.post("/reprocess", status_code=202)
def reprocess_rejected_offers(
    store_key: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    _auth: None = Depends(_authorize),
):
    """Queue only records explicitly marked retryable by the validation pipeline."""
    try:
        from app.workers.ingestion_tasks import reprocess_failed_offers
        job = reprocess_failed_offers.apply_async(
            kwargs={"store_key": store_key, "limit": limit}, queue="validation"
        )
        return {"status": "queued", "store": store_key, "limit": limit, "job_id": str(job.id)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="reprocessing_queue_unavailable") from exc
