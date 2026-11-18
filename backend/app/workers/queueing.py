"""Typed producer helpers for catalog-first tasks."""
from __future__ import annotations
from typing import Any, Mapping
from uuid import UUID
from app.workers.celery_app import celery_app, queue_is_configured

TASKS = {
    "discover": "app.workers.tasks.discover_store_products",
    "fetch": "app.workers.tasks.fetch_store_offers",
    "normalize": "app.workers.tasks.normalize_offer",
    "match": "app.workers.tasks.match_offer_to_variant",
    "validate": "app.workers.tasks.validate_offer",
    "refresh": "app.workers.tasks.refresh_price_and_stock",
    "quarantine": "app.workers.tasks.quarantine_failed_connector",
    "reprocess": "app.workers.tasks.reprocess_failed_offers",
}
class QueueNotConfigured(RuntimeError):
    pass

def _enqueue(stage: str, payload: Mapping[str, Any]):
    if stage not in TASKS:
        raise ValueError(f"unsupported ingestion stage: {stage}")
    if not queue_is_configured():
        raise QueueNotConfigured("SCENTHUNTER_REDIS_URL is not configured; background ingestion is disabled")
    import json
    safe_payload = json.loads(json.dumps(dict(payload), allow_nan=False))
    return celery_app.send_task(TASKS[stage], kwargs={"payload": safe_payload})

def enqueue_discovery(store_id: UUID | str, *, cursor: str | None = None, limit: int = 100):
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    return _enqueue("discover", {"store_id": str(store_id), "cursor": cursor, "limit": limit})

def enqueue_offer_fetch(store_id: UUID | str, external_product_id: str):
    if not str(external_product_id).strip():
        raise ValueError("external_product_id is required")
    return _enqueue("fetch", {"store_id": str(store_id), "external_product_id": str(external_product_id)})

def enqueue_stage(stage: str, *, ingestion_raw_id: UUID | str, extra: Mapping[str, Any] | None = None):
    if stage not in {"normalize", "match", "validate", "refresh", "quarantine", "reprocess"}:
        raise ValueError(f"unsupported downstream stage: {stage}")
    payload = {"ingestion_raw_id": str(ingestion_raw_id)}
    if extra:
        payload.update(dict(extra))
    return _enqueue(stage, payload)
