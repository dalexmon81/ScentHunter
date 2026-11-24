"""Notino feed handlers for the catalog-first background worker."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db import make_engine
from app.models import Offer, Store
from app.connectors.base import ConnectorUnavailable
from app.repositories.ingestion_runs import (
    finish_ingestion_run,
    record_ingestion_progress,
    start_ingestion_run,
)
from app.workers.queueing import enqueue_discovery, enqueue_offer_fetch
from app.workers.runtime import register_handler
from app.connectors.notino_feed import NotinoAffiliateFeedConnector
from app.discovery.dispatch import dispatch_discovered_products
from app.offers.ingestion import persist_connector_record
from scenthunter_next_engine.next_engine_service import NextEngineService
from app.monitoring.connector_health import record_connector_failure, record_connector_success
from app.pricing.offer_refresh import refresh_offer_observation

_SESSION_FACTORY = None
_CONNECTOR: NotinoAffiliateFeedConnector | None = None
_MATCHER: NextEngineService | None = None


def _sessions():
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        _SESSION_FACTORY = sessionmaker(bind=make_engine(), expire_on_commit=False)
    return _SESSION_FACTORY


def _connector() -> NotinoAffiliateFeedConnector:
    global _CONNECTOR
    if _CONNECTOR is None:
        _CONNECTOR = NotinoAffiliateFeedConnector()
    return _CONNECTOR


def _matcher() -> NextEngineService:
    """Load the read-only legacy catalog used only as a conservative fallback matcher."""
    global _MATCHER
    if _MATCHER is None:
        catalog_path = Path(__file__).resolve().parents[2] / "product_catalog.json"
        if not catalog_path.is_file():
            raise RuntimeError(f"Notino fallback matcher catalog is missing: {catalog_path}")
        _MATCHER = NextEngineService.from_catalog_file(catalog_path)
    return _MATCHER


def _store_id(payload: Mapping[str, Any]) -> UUID:
    try:
        return UUID(str(payload["store_id"]))
    except (KeyError, TypeError, ValueError):
        raise ValueError("store_id must be a valid UUID") from None


def _active_notino_store(session, store_id: UUID) -> Store:
    store = session.get(Store, store_id)
    if store is None or store.slug != "notino-fr" or store.status != "active":
        raise ValueError("store_id must identify the active notino-fr catalog store")
    return store


def handle_notino_discovery(payload: Mapping[str, Any]) -> dict[str, Any]:
    store_id = _store_id(payload)
    limit = int(payload.get("limit", 500))
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    cursor = payload.get("cursor")
    if cursor is not None and not str(cursor).isdigit():
        raise ValueError("cursor must be a non-negative integer")

    with _sessions()() as session, session.begin():
        _active_notino_store(session, store_id)
        run_id = start_ingestion_run(session, store_id=store_id)

    try:
        connector = _connector()
        products = asyncio.run(
            connector.discover_products(
                cursor=str(cursor) if cursor is not None else None,
                limit=limit,
            )
        )
        with _sessions()() as session, session.begin():
            record_connector_success(session, store_id=store_id)
        # Discovery dispatch never filters on canonical matching. Every
        # reference reaches the shared fetch/offer gate for a consistent decision.
        dispatch = dispatch_discovered_products(
            store_id, products, cursor=str(cursor) if cursor is not None else None,
            limit=limit, enqueue_fetch=enqueue_offer_fetch,
            enqueue_next_page=enqueue_discovery,
        )
        queued = dispatch.fetch_jobs_queued
        next_cursor = dispatch.next_cursor
        errors = list(dispatch.errors)

        with _sessions()() as session, session.begin():
            record_ingestion_progress(
                session,
                run_id=run_id,
                products_discovered=len(products),
                error="; ".join(errors) if errors else None,
            )
            finish_ingestion_run(
                session,
                run_id=run_id,
                status="partial" if errors else "completed",
            )
        return {
            "status": "partial" if errors else "completed",
            "run_id": str(run_id),
            "products_discovered": len(products),
            "fetch_jobs_queued": queued,
            "products_not_queued": len(products) - queued,
            "next_cursor": next_cursor,
            "errors": errors,
        }
    except Exception as exc:
        with _sessions()() as session, session.begin():
            if isinstance(exc, ConnectorUnavailable):
                record_connector_failure(session, store_id=store_id, error=str(exc))
            record_ingestion_progress(
                session, run_id=run_id,
                error=f"{type(exc).__name__}:{exc}",
            )
            finish_ingestion_run(session, run_id=run_id, status="failed")
        raise


def handle_notino_fetch(payload: Mapping[str, Any]) -> dict[str, Any]:
    store_id = _store_id(payload)
    external_id = str(payload.get("external_product_id") or "").strip()
    if not external_id:
        raise ValueError("external_product_id is required")

    with _sessions()() as session, session.begin():
        _active_notino_store(session, store_id)
        run_id = start_ingestion_run(session, store_id=store_id)

    try:
        raw_record = asyncio.run(_connector().fetch_product(external_id))
        with _sessions()() as session, session.begin():
            record_connector_success(session, store_id=store_id)
        if raw_record is None:
            with _sessions()() as session, session.begin():
                record_ingestion_progress(
                    session, run_id=run_id, products_discovered=1,
                    offers_rejected=1, error="notino_offer_not_found_in_latest_feed_snapshot",
                )
                finish_ingestion_run(session, run_id=run_id, status="partial")
            return {"status": "not_found", "run_id": str(run_id), "external_product_id": external_id}

        with _sessions()() as session, session.begin():
            store = _active_notino_store(session, store_id)
            existing = session.scalar(
                select(Offer.id).where(
                    Offer.store_id == store.id,
                    Offer.external_product_id == external_id,
                ).limit(1)
            )
            result = persist_connector_record(
                session,
                connector=_connector(),
                store_id=store.id,
                raw_record=dict(raw_record),
                matcher=_matcher(),
            )
            promoted = result.status == "promoted"
            record_ingestion_progress(
                session,
                run_id=run_id,
                products_discovered=1,
                offers_created=1 if promoted and existing is None else 0,
                offers_updated=1 if promoted and existing is not None else 0,
                offers_rejected=0 if promoted else 1,
                error=result.reason,
            )
            finish_ingestion_run(
                session,
                run_id=run_id,
                status="completed" if promoted else "partial",
            )
        return {
            "status": result.status,
            "run_id": str(run_id),
            "ingestion_raw_id": str(result.ingestion_raw_id),
            "offer_id": str(result.offer_id) if result.offer_id else None,
            "product_variant_id": str(result.product_variant_id) if result.product_variant_id else None,
            "reason": result.reason,
        }
    except Exception as exc:
        with _sessions()() as session, session.begin():
            if isinstance(exc, ConnectorUnavailable):
                record_connector_failure(session, store_id=store_id, error=str(exc))
            record_ingestion_progress(
                session, run_id=run_id,
                offers_rejected=1, error=f"{type(exc).__name__}:{exc}",
            )
            finish_ingestion_run(session, run_id=run_id, status="failed")
        raise



def handle_notino_refresh(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Refresh one existing Notino offer without changing its canonical identity."""
    store_id = _store_id(payload)
    external_id = str(payload.get("external_product_id") or "").strip()
    if not external_id:
        raise ValueError("external_product_id is required")

    with _sessions()() as session, session.begin():
        store = _active_notino_store(session, store_id)
        offer = session.scalar(select(Offer).where(
            Offer.store_id == store.id,
            Offer.external_product_id == external_id,
            Offer.status == "active",
        ).limit(1))
        if offer is None:
            raise ValueError("active Notino offer not found for refresh")
        offer_id = offer.id
        run_id = start_ingestion_run(session, store_id=store.id)

    try:
        observation = asyncio.run(_connector().fetch_price_and_stock(external_id))
        with _sessions()() as session, session.begin():
            record_connector_success(session, store_id=store_id)
        if not isinstance(observation, Mapping):
            raise ValueError("Notino refresh returned no structured observation")
        parsed = _connector().parse_raw(observation)
        validation = _connector().validate_offer(parsed)
        if not validation.valid or parsed.get("currency_explicit") is not True:
            errors = validation.errors or ("currency_not_explicit",)
            raise ValueError("Notino refresh rejected: " + ";".join(errors))
        with _sessions()() as session, session.begin():
            _active_notino_store(session, store_id)
            refreshed_id = refresh_offer_observation(
                session, offer_id=offer_id, observation={
                    "price": parsed.get("price"),
                    "currency": parsed.get("currency"),
                    "availability": parsed.get("availability"),
                    "product_url": parsed.get("product_url"),
                    "url": parsed.get("url"),
                    "captured_at": observation.get("captured_at"),
                    "source_updated_at": observation.get("source_updated_at"),
                    "raw_xml": observation.get("raw_xml"),
                }, source=str(parsed.get("source") or "notino_authorized_cj_viv_xml_feed"),
                currency_explicit=parsed.get("currency_explicit") is True,
            )
            record_ingestion_progress(session, run_id=run_id, offers_updated=1)
            finish_ingestion_run(session, run_id=run_id, status="completed")
        return {"status": "refreshed", "run_id": str(run_id), "offer_id": str(refreshed_id)}
    except Exception as exc:
        with _sessions()() as session, session.begin():
            if isinstance(exc, ConnectorUnavailable):
                record_connector_failure(session, store_id=store_id, error=str(exc))
            record_ingestion_progress(
                session, run_id=run_id, offers_rejected=1,
                error=f"{type(exc).__name__}:{exc}",
            )
            finish_ingestion_run(session, run_id=run_id, status="partial")
        raise


def register_notino_handlers() -> None:
    """Register the validated Notino discovery, fetch and refresh stages."""
    register_handler("discover", handle_notino_discovery)
    register_handler("fetch", handle_notino_fetch)
    register_handler("refresh", handle_notino_refresh)
