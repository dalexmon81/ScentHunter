"""Safe, offer-scoped on-demand refresh endpoint for the catalog-first API."""
from __future__ import annotations

import os
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.db import make_session_factory
from app.models import Offer, Store

router = APIRouter()


def queue_offer_refresh(
    offer_id: UUID,
    *,
    session_factory=None,
    redis_factory=None,
    enqueue=None,
):
    """Queue refresh only for a persisted active offer; never trust client store/SKU."""
    factory = session_factory or make_session_factory()
    try:
        with factory() as session:
            row = session.execute(
                select(Offer.external_product_id, Store.slug)
                .join(Store, Offer.store_id == Store.id)
                .where(
                    Offer.id == offer_id,
                    Offer.status == "active",
                    Store.status == "active",
                )
            ).one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail="active_offer_not_found")
            external_product_id, store_key = row
            if not external_product_id or not str(external_product_id).strip():
                raise HTTPException(status_code=409, detail="offer_has_no_refreshable_retailer_id")
    finally:
        # The Phase 2 engine is created per factory; close its pool after this request.
        factory.kw["bind"].dispose()

    if redis_factory is None:
        from redis import Redis
        from app.workers.celery_app import BROKER_URL
        redis_factory = lambda: Redis.from_url(BROKER_URL, decode_responses=True)

    try:
        client = redis_factory()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="refresh_queue_unavailable") from exc
    cooldown_key = f"scenthunter:detail-refresh:{offer_id}"
    try:
        configured_cooldown = int(os.environ.get("SCENTHUNTER_DETAIL_REFRESH_COOLDOWN_SECONDS", "300"))
    except (TypeError, ValueError):
        configured_cooldown = 300
    cooldown_seconds = min(3600, max(30, configured_cooldown))
    try:
        try:
            acquired = client.set(cooldown_key, "queued", nx=True, ex=cooldown_seconds)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="refresh_queue_unavailable") from exc

        if not acquired:
            return {"status": "already_queued", "offer_id": str(offer_id)}

        try:
            if enqueue is None:
                from app.workers.ingestion_tasks import enqueue_product_detail_refresh
                enqueue = enqueue_product_detail_refresh
            job_id = enqueue(store_key, str(external_product_id))
        except Exception as exc:
            try:
                client.delete(cooldown_key)
            except Exception:
                pass
            raise HTTPException(status_code=503, detail="refresh_enqueue_failed") from exc

        return {"status": "queued", "offer_id": str(offer_id), "job_id": str(job_id)}
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


@router.post("/catalog/offers/{offer_id}/refresh", status_code=202)
def refresh_catalog_offer(offer_id: UUID):
    """Refresh a known offer by opaque UUID; store and retailer ID are DB-derived."""
    return queue_offer_refresh(offer_id)
