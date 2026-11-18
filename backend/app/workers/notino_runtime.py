"""Notino feed handlers for the catalog-first Celery worker runtime.

Handlers are synchronous Celery entry points. Connector I/O remains async and
runs only in the background worker; HTTP search never invokes this module.
"""
from __future__ import annotations

import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db import make_engine
from app.models import Offer, Store
from app.workers.ingestion_run import (
    finish_ingestion_run,
    record_ingestion_progress,
    start_ingestion_run,
)
from app.workers.queueing import enqueue_discovery, enqueue_offer_fetch
from app.workers.runtime import register_handler
from app.connectors.notino_feed import NotinoAffiliateFeedConnector
from app.services.connector_ingestion import persist_connector_record
from scenthunter_next_engine.next_engine_service import NextEngineService

_CATALOG_PATH = Path(__file__).resolve().parents[2] / "product_catalog.json"
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
    global _MATCHER
    if _MATCHER is None:
        if not _CATALOG_PATH.is_file():
            raise RuntimeError("canonical matcher catalog file is missing")
        _MATCHER = NextEngineService.from_catalog_file(_CATALOG_PATH)
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
    limit = int(payload.get("limit", 100))
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    cursor = payload.get("cursor")
    if cursor is not None and not str(cursor).isdigit():
        raise ValueError("cursor must be a non-negative integer")

    with _sessions()() as session, session.begin():
        _active_notino_store(session, store_id)
        run_id = start_ingestion_run(session, store_id=store_id)

    try:
        products = asyncio.run(
            _connector().discover_products(
                cursor=str(cursor) if cursor is not None else None,
                limit=limit,
            )
        )
        queued = 0
        errors: list[str] = []
        for product in products:
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
            "next_cursor": next_cursor,
            "errors": errors,
        }
    except Exception as exc:
        with _sessions()() as session, session.begin():
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
            record_ingestion_progress(
                session, run_id=run_id,
                offers_rejected=1, error=f"{type(exc).__name__}:{exc}",
            )
            finish_ingestion_run(session, run_id=run_id, status="failed")
        raise


def register_notino_handlers() -> None:
    """Register only the two Notino stages implemented and validated here."""
    register_handler("discover", handle_notino_discovery)
    register_handler("fetch", handle_notino_fetch)
