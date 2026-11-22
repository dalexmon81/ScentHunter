"""Worker orchestration for the legacy-scraper connector adapters.

The existing retailer parsers remain unchanged. This module routes their
background discovery/fetch/refresh work through the catalog persistence gates.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select

from app.connectors.base import ConnectorUnavailable
from app.connectors.legacy_scrapers import (
    build_legacy_connector,
    connector_key_for_store_slug,
)
from app.models import Offer, Store
from app.services.connector_health import record_connector_failure, record_connector_success
from app.services.connector_ingestion import persist_connector_record
from app.services.offer_refresh import refresh_offer_observation
from app.workers import notino_runtime
from app.workers.ingestion_run import (
    finish_ingestion_run,
    record_ingestion_progress,
    start_ingestion_run,
)
from app.workers.queueing import enqueue_discovery, enqueue_offer_fetch
from app.workers.runtime import register_handler


def _store_id(payload: Mapping[str, Any]) -> UUID:
    try:
        return UUID(str(payload["store_id"]))
    except (KeyError, TypeError, ValueError):
        raise ValueError("store_id must be a valid UUID") from None


def _active_store(store_id: UUID) -> tuple[Store, str]:
    with notino_runtime._sessions()() as session:
        store = session.get(Store, store_id)
        if store is None or store.status != "active":
            raise ValueError("store_id must identify an active catalog store")
        connector_key = connector_key_for_store_slug(store.slug)
        if connector_key is None:
            raise ValueError(f"no legacy scraper connector is registered for store {store.slug}")
        return store, connector_key


def _connector_for(store_slug: str):
    connector_key = connector_key_for_store_slug(store_slug)
    if connector_key is None:
        raise ValueError(f"unsupported legacy store slug: {store_slug}")
    return build_legacy_connector(connector_key)


def handle_legacy_discovery(payload: Mapping[str, Any]) -> dict[str, Any]:
    store_id = _store_id(payload)
    store, connector_key = _active_store(store_id)
    limit = int(payload.get("limit", 100))
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    cursor = payload.get("cursor")
    if cursor is not None and not str(cursor).isdigit():
        raise ValueError("cursor must be a non-negative integer")

    with notino_runtime._sessions()() as session, session.begin():
        run_id = start_ingestion_run(session, store_id=store_id)

    connector = build_legacy_connector(connector_key, allowed_domain=store.domain)
    try:
        products = asyncio.run(connector.discover_products(
            cursor=str(cursor) if cursor is not None else None,
            limit=limit,
        ))
        with notino_runtime._sessions()() as session, session.begin():
            record_connector_success(session, store_id=store_id)

        queued = skipped = 0
        errors: list[str] = []
        for product in products:
            if not notino_runtime._is_unique_canonical_candidate(
                connector, store_id, product.raw_payload
            ):
                skipped += 1
                continue
            try:
                enqueue_offer_fetch(store_id, product.external_product_id)
                queued += 1
            except Exception as exc:
                errors.append(
                    f"enqueue_fetch:{product.external_product_id}:{type(exc).__name__}:{exc}"
                )

        next_cursor = None
        if len(products) == limit:
            next_cursor = str(int(cursor or 0) + len(products))
            try:
                enqueue_discovery(store_id, cursor=next_cursor, limit=limit)
            except Exception as exc:
                errors.append(f"enqueue_next_page:{type(exc).__name__}:{exc}")

        with notino_runtime._sessions()() as session, session.begin():
            record_ingestion_progress(
                session, run_id=run_id, products_discovered=len(products),
                error="; ".join(errors) if errors else None,
            )
            finish_ingestion_run(
                session, run_id=run_id, status="partial" if errors else "completed"
            )
        return {
            "status": "partial" if errors else "completed",
            "store": store.slug,
            "run_id": str(run_id),
            "products_discovered": len(products),
            "canonical_candidates_skipped": skipped,
            "fetch_jobs_queued": queued,
            "next_cursor": next_cursor,
            "errors": errors,
        }
    except Exception as exc:
        with notino_runtime._sessions()() as session, session.begin():
            if isinstance(exc, ConnectorUnavailable):
                record_connector_failure(session, store_id=store_id, error=str(exc))
            record_ingestion_progress(
                session, run_id=run_id, error=f"{type(exc).__name__}:{exc}"
            )
            finish_ingestion_run(session, run_id=run_id, status="failed")
        raise


def handle_legacy_fetch(payload: Mapping[str, Any]) -> dict[str, Any]:
    store_id = _store_id(payload)
    store, connector_key = _active_store(store_id)
    external_id = str(payload.get("external_product_id") or "").strip()
    if not external_id:
        raise ValueError("external_product_id is required")

    with notino_runtime._sessions()() as session, session.begin():
        run_id = start_ingestion_run(session, store_id=store_id)

    connector = build_legacy_connector(connector_key)
    try:
        record = asyncio.run(connector.fetch_product(external_id))
        if not isinstance(record, Mapping):
            raise LookupError(f"{store.slug}_product_not_found")
        with notino_runtime._sessions()() as session, session.begin():
            record_connector_success(session, store_id=store_id)
            result = persist_connector_record(
                session, connector=connector, store_id=store_id,
                raw_record=dict(record), matcher=notino_runtime._matcher(),
            )
            record_ingestion_progress(
                session, run_id=run_id, products_discovered=1,
                offers_created=1 if result.status == "promoted" else 0,
                offers_rejected=1 if result.status == "rejected" else 0,
            )
            finish_ingestion_run(
                session, run_id=run_id,
                status="completed" if result.status == "promoted" else "partial",
            )
        return {
            "status": result.status,
            "store": store.slug,
            "run_id": str(run_id),
            "offer_id": str(result.offer_id) if result.offer_id else None,
            "product_variant_id": str(result.product_variant_id) if result.product_variant_id else None,
            "reason": result.reason,
        }
    except Exception as exc:
        with notino_runtime._sessions()() as session, session.begin():
            if isinstance(exc, ConnectorUnavailable):
                record_connector_failure(session, store_id=store_id, error=str(exc))
            record_ingestion_progress(
                session, run_id=run_id, offers_rejected=1,
                error=f"{type(exc).__name__}:{exc}",
            )
            finish_ingestion_run(session, run_id=run_id, status="partial")
        raise


def handle_legacy_refresh(payload: Mapping[str, Any]) -> dict[str, Any]:
    store_id = _store_id(payload)
    store, connector_key = _active_store(store_id)
    external_id = str(payload.get("external_product_id") or "").strip()
    if not external_id:
        raise ValueError("external_product_id is required")

    with notino_runtime._sessions()() as session, session.begin():
        run_id = start_ingestion_run(session, store_id=store_id)

    connector = build_legacy_connector(connector_key)
    try:
        observation = asyncio.run(connector.fetch_price_and_stock(external_id))
        raw_record = observation.get("raw_record")
        parsed = connector.parse_raw(raw_record if isinstance(raw_record, Mapping) else observation)
        if parsed.get("currency_explicit") is not True:
            raise ValueError("currency_not_explicit_in_retailer_source")
        if not connector.validate_offer(parsed).valid:
            raise ValueError("refreshed_offer_failed_validation")
        with notino_runtime._sessions()() as session, session.begin():
            record_connector_success(session, store_id=store_id)
            offer = session.scalar(select(Offer).where(
                Offer.store_id == store_id,
                Offer.status == "active",
                or_(Offer.external_product_id == external_id, Offer.url == external_id),
            ).order_by(Offer.captured_at.desc()).limit(1))
            if offer is None:
                raise LookupError("active_offer_not_found_for_refresh")
            refresh_offer_observation(
                session, offer_id=offer.id,
                observation={
                    "price": parsed.get("price"),
                    "currency": parsed.get("currency"),
                    "availability": parsed.get("availability"),
                    "product_url": parsed.get("product_url"),
                    "url": parsed.get("url"),
                    "captured_at": observation.get("captured_at"),
                    "raw_record": dict(raw_record) if isinstance(raw_record, Mapping) else dict(observation),
                },
                source=str(parsed.get("source") or f"{connector.store_key}_legacy_scraper"),
                currency_explicit=parsed.get("currency_explicit") is True,
            )
            record_ingestion_progress(session, run_id=run_id, offers_updated=1)
            finish_ingestion_run(session, run_id=run_id, status="completed")
        return {"status": "refreshed", "store": store.slug, "run_id": str(run_id)}
    except Exception as exc:
        with notino_runtime._sessions()() as session, session.begin():
            if isinstance(exc, ConnectorUnavailable):
                record_connector_failure(session, store_id=store_id, error=str(exc))
            record_ingestion_progress(
                session, run_id=run_id, offers_rejected=1,
                error=f"{type(exc).__name__}:{exc}",
            )
            finish_ingestion_run(session, run_id=run_id, status="partial")
        raise


def _dispatch(stage: str, payload: Mapping[str, Any]):
    store_id = _store_id(payload)
    with notino_runtime._sessions()() as session:
        store = session.get(Store, store_id)
        slug = store.slug if store is not None else None
    if slug == "notino-fr":
        handler = {
            "discover": notino_runtime.handle_notino_discovery,
            "fetch": notino_runtime.handle_notino_fetch,
            "refresh": notino_runtime.handle_notino_refresh,
        }[stage]
        return handler(payload)
    if stage == "discover":
        return handle_legacy_discovery(payload)
    if stage == "fetch":
        return handle_legacy_fetch(payload)
    return handle_legacy_refresh(payload)


def register_catalog_handlers() -> None:
    """Register dispatchers while preserving the dedicated Notino implementation."""
    register_handler("discover", lambda payload: _dispatch("discover", payload))
    register_handler("fetch", lambda payload: _dispatch("fetch", payload))
    register_handler("refresh", lambda payload: _dispatch("refresh", payload))
