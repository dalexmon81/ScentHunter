"""Typed producer helpers for implemented catalog worker tasks."""
from __future__ import annotations

import json
import os
from typing import Any, Mapping
from uuid import UUID

TASKS = {
    "discover": "app.workers.tasks.discover_store_products",
    "fetch": "app.workers.tasks.fetch_store_offers",
    "refresh": "app.workers.tasks.refresh_price_and_stock",
}


class QueueNotConfigured(RuntimeError):
    pass


def _backend() -> str:
    value = os.environ.get("SCENTHUNTER_QUEUE_BACKEND", "redis").strip().lower()
    if value not in {"sqlite", "redis", "postgres"}:
        raise RuntimeError("SCENTHUNTER_QUEUE_BACKEND must be sqlite, redis or postgres")
    return value


def _enqueue(stage: str, payload: Mapping[str, Any]):
    if stage not in TASKS:
        raise ValueError(f"unsupported ingestion stage: {stage}")
    safe_payload = json.loads(json.dumps(dict(payload), allow_nan=False))
    backend = _backend()
    if backend == "sqlite":
        from app.workers.sqlite_queue import enqueue
        return enqueue(stage, safe_payload)
    if backend == "postgres":
        from app.workers.postgres_queue import enqueue
        return enqueue(stage, safe_payload)
    from app.workers.celery_app import celery_app, queue_is_configured
    if not queue_is_configured():
        raise QueueNotConfigured("SCENTHUNTER_REDIS_URL is not configured")
    return celery_app.send_task(TASKS[stage], kwargs={"payload": safe_payload})


def enqueue_discovery(store_id: UUID | str, *, cursor: str | None = None, limit: int = 100):
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    return _enqueue("discover", {"store_id": str(store_id), "cursor": cursor, "limit": limit})


def enqueue_offer_fetch(store_id: UUID | str, external_product_id: str):
    if not str(external_product_id).strip():
        raise ValueError("external_product_id is required")
    return _enqueue("fetch", {"store_id": str(store_id), "external_product_id": str(external_product_id)})


def enqueue_offer_refresh(store_id: UUID | str, external_product_id: str):
    if not str(external_product_id).strip():
        raise ValueError("external_product_id is required")
    return _enqueue("refresh", {"store_id": str(store_id), "external_product_id": str(external_product_id)})
