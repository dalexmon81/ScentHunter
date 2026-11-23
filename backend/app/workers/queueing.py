"""PostgreSQL-only producer helpers for canonical catalog ingestion."""
from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import UUID

TASKS = {
    "discover": "app.workers.tasks.discover_store_products",
    "fetch": "app.workers.tasks.fetch_store_offers",
    "refresh": "app.workers.tasks.refresh_price_and_stock",
}


class QueueNotConfigured(RuntimeError):
    pass


def _enqueue(stage: str, payload: Mapping[str, Any]):
    if stage not in TASKS:
        raise ValueError(f"unsupported ingestion stage: {stage}")
    from app.workers.postgres_queue import enqueue
    safe_payload = json.loads(json.dumps(dict(payload), allow_nan=False))
    return enqueue(stage, safe_payload)


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
