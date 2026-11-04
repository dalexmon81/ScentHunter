"""Redis/Celery tasks for the catalog-first ingestion pipeline.

Each task is idempotent at the evidence boundary where possible. Raw retailer
and parser evidence is retained in ingestion_raw.raw_payload alongside the
normalized offer fields. Matching and promotion remain separate gates.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import hashlib
from uuid import UUID
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select

from app.db import make_session_factory
from app.connectors.runtime_registry import build_connectors, get_connector
from app.models import IngestionArtifact, IngestionDeadLetter, IngestionRaw, IngestionRun, Offer, Store
from app.matching.offer_matcher import match_staged_offer
from app.services.product_normalization import normalize_product
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
QUARANTINE_AFTER = max(1, int(__import__("os").environ.get("SCENTHUNTER_CONNECTOR_QUARANTINE_AFTER", "3")))

class IngestionTask(celery_app.Task):
    abstract = True
    autoretry_for = (TimeoutError, ConnectionError, OSError)
    retry_backoff = True
    retry_backoff_max = 900
    retry_jitter = True
    max_retries = 5

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        try:
            record_dead_letter.apply_async(
                kwargs={
                    "task_name": self.name,
                    "task_id": task_id,
                    "args_repr": repr(args)[:2000],
                    "kwargs_repr": repr(kwargs)[:2000],
                    "error": f"{type(exc).__name__}: {exc}"[:1000],
                },
                queue="dead_letter",
            )
            store_key = kwargs.get("store_key") or (args[0] if args else None)
            if store_key and self.name != "app.workers.ingestion_tasks.quarantine_failed_connector":
                factory = make_session_factory()
                try:
                    with factory() as session:
                        store = session.scalar(select(Store).where(Store.slug == store_key))
                        if store is not None:
                            run = session.scalar(select(IngestionRun).where(
                                IngestionRun.store_id == store.id,
                                IngestionRun.status == "running",
                            ).order_by(IngestionRun.started_at.desc()).limit(1))
                            if run is None:
                                run = IngestionRun(store_id=store.id, status="failed", errors=[])
                                session.add(run)
                            run.status = "failed"
                            run.finished_at = datetime.now(timezone.utc)
                            run.errors = [{"task": self.name, "task_id": task_id,
                                           "error": f"{type(exc).__name__}: {exc}"[:500]}]
                            session.commit()
                finally:
                    factory.kw["bind"].dispose()
                quarantine_failed_connector.apply_async(args=[store_key], queue="dead_letter")
        except Exception:
            logger.exception("Unable to enqueue dead-letter record for %s", task_id)

def _run(coro):
    return asyncio.run(coro)

def _json_safe(value: Any):
    if isinstance(value, bytes):
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)[:2000]

def _persist_raw_artifacts(store_key: str, run_id: str | None, artifacts: list[dict]) -> list[str]:
    """Persist exact source bytes (or deterministic JSON evidence) once per hash."""
    factory = make_session_factory()
    artifact_ids = []
    try:
        with factory() as session:
            store = session.scalar(select(Store).where(Store.slug == store_key))
            if store is None:
                raise ValueError(f"connector_store_not_configured:{store_key}")
            if store.status != "active":
                raise ValueError(f"connector_store_not_active:{store_key}")
            for artifact in artifacts:
                raw = artifact.get("data")
                fmt = str(artifact.get("format") or "json").lower()
                if isinstance(raw, bytes):
                    blob = raw
                elif isinstance(raw, bytearray):
                    blob = bytes(raw)
                elif isinstance(raw, str) and fmt == "html":
                    blob = raw.encode("utf-8")
                else:
                    blob = json.dumps(_json_safe(raw), ensure_ascii=False, sort_keys=True).encode("utf-8")
                digest = hashlib.sha256(blob).hexdigest()
                existing = session.scalar(select(IngestionArtifact).where(
                    IngestionArtifact.store_id == store.id,
                    IngestionArtifact.sha256 == digest,
                ))
                if existing is not None:
                    artifact_ids.append(str(existing.id))
                    continue
                row = IngestionArtifact(
                    store_id=store.id,
                    ingestion_run_id=UUID(str(run_id)) if run_id else None,
                    artifact_format=fmt,
                    content_type=artifact.get("content_type"),
                    source_url=artifact.get("source_url"),
                    sha256=digest,
                    size_bytes=len(blob),
                    raw_data=blob,
                    metadata_json=_json_safe(artifact.get("metadata") or {}),
                )
                session.add(row)
                session.flush()
                artifact_ids.append(str(row.id))
            session.commit()
        return artifact_ids
    finally:
        factory.kw["bind"].dispose()

def _stage_record(store_key: str, record, discovery_evidence: dict | None = None) -> str:
    factory = make_session_factory()
    try:
        with factory() as session:
            store = session.scalar(select(Store).where(Store.slug == store_key))
            if store is None:
                raise ValueError(f"connector_store_not_configured:{store_key}")
            if store.status != "active":
                raise ValueError(f"connector_store_not_active:{store_key}")
            payload = record.to_dict()
            # Keep fields at the root for existing matcher/promotion contracts;
            # preserve source evidence separately for replay and audit.
            payload["_raw_evidence"] = {
                "format": "connector_discovery_and_parsed_record",
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "discovery": _json_safe(discovery_evidence or {}),
                "parser_output": _json_safe(payload),
            }
            existing = session.scalar(select(IngestionRaw).where(
                IngestionRaw.store_id == store.id,
                IngestionRaw.external_product_id == record.external_product_id,
                IngestionRaw.status.in_(("pending", "unmatched", "matched")),
            ).order_by(IngestionRaw.created_at.desc()).limit(1))
            if existing is not None:
                # Preserve original capture and append latest observation history
                # in the evidence envelope rather than creating duplicate rows.
                evidence = existing.raw_payload or {}
                history = evidence.get("_refresh_history", [])
                history.append(payload["_raw_evidence"])
                evidence["_refresh_history"] = history[-20:]
                for key, value in payload.items():
                    if key != "_raw_evidence":
                        evidence[key] = value
                existing.raw_payload = evidence
                existing.status = "pending"
                existing.product_variant_id = None
                existing.match_method = None
                existing.match_confidence = None
                existing.rejection_reason = None
                raw_id = existing.id
            else:
                raw = IngestionRaw(
                    store_id=store.id,
                    raw_payload=payload,
                    external_product_id=record.external_product_id,
                    status="pending",
                )
                session.add(raw)
                session.flush()
                raw_id = raw.id
            session.commit()
            return str(raw_id)
    finally:
        factory.kw["bind"].dispose()

@celery_app.task(bind=True, base=IngestionTask, name="app.workers.ingestion_tasks.discover_store_products")
def discover_store_products(self, store_key: str):
    connector = get_connector(store_key)
    factory = make_session_factory()
    try:
        with factory() as session:
            store = session.scalar(select(Store).where(Store.slug == store_key))
            if store is None:
                raise ValueError(f"connector_store_not_configured:{store_key}")
            if store.status != "active":
                return {"store": store_key, "status": "inactive", "queued": 0}
            run = IngestionRun(store_id=store.id, status="running", errors=[])
            session.add(run)
            session.flush()
            run_id = str(run.id)
            session.commit()
    finally:
        factory.kw["bind"].dispose()
    products = _run(connector.discover_products())
    raw_artifacts = list(getattr(connector, "_raw_artifacts", []) or [])
    if not raw_artifacts:
        raw_artifacts = [{"format": "json", "data": list(products), "metadata": {"kind": "discovery_result"}}]
    artifact_ids = _persist_raw_artifacts(store_key, run_id, raw_artifacts)
    staged = []
    # Discovery and offer extraction must share this connector instance:
    # connector adapters keep their parsed discovery cache in memory, and
    # Celery tasks may execute on different workers. Queueing only the product
    # key here would lose that cache and silently produce zero offers.
    for product in products:
        product_key = str(product.get("externalProductId") or product.get("external_product_id") or product.get("url") or "").strip()
        if not product_key:
            continue
        records = _run(connector.fetch_offers(product_key))
        for record in records:
            evidence = _json_safe(dict(product))
            evidence["raw_artifact_ids"] = artifact_ids
            raw_id = _stage_record(store_key, record, evidence)
            normalize_offer.apply_async(args=[raw_id], queue="validation")
            staged.append(raw_id)
    factory = make_session_factory()
    try:
        with factory() as session:
            run = session.scalar(select(IngestionRun).join(Store).where(
                Store.slug == store_key, IngestionRun.status == "running"
            ).order_by(IngestionRun.started_at.desc()).limit(1))
            if run is not None:
                run.status = "completed"
                run.products_discovered = len(products)
                run.finished_at = datetime.now(timezone.utc)
                store = session.get(Store, run.store_id)
                store.last_successful_sync_at = run.finished_at
                session.commit()
    finally:
        factory.kw["bind"].dispose()
    return {"store": store_key, "discovered": len(products), "offers_staged": len(staged), "raw_ids": staged}

@celery_app.task(bind=True, base=IngestionTask, name="app.workers.ingestion_tasks.fetch_store_offers")
def fetch_store_offers(self, store_key: str, product_key: str, discovery_evidence: dict | None = None):
    connector = get_connector(store_key)
    records = _run(connector.fetch_offers(product_key))
    ids = []
    for record in records:
        raw_id = _stage_record(store_key, record, discovery_evidence)
        ids.append(raw_id)
        normalize_offer.apply_async(args=[raw_id], queue="validation")
    return {"store": store_key, "product": product_key, "offers_staged": len(ids), "raw_ids": ids}

@celery_app.task(bind=True, base=IngestionTask, name="app.workers.ingestion_tasks.normalize_offer")
def normalize_offer(self, raw_id: str):
    factory = make_session_factory()
    try:
        with factory() as session:
            raw = session.get(IngestionRaw, UUID(str(raw_id)))
            if raw is None or raw.status not in {"pending", "unmatched"}:
                return {"raw_id": raw_id, "status": "skipped"}
            payload = raw.raw_payload or {}
            normalized = normalize_product(
                str(payload.get("brand") or ""),
                str(payload.get("title") or ""),
                concentration=payload.get("concentration"),
                size_ml=payload.get("sizeMl"),
            )
            payload["fragrance"] = normalized.fragrance_name
            payload["concentration"] = normalized.concentration
            payload["sizeMl"] = normalized.size_ml
            payload["_normalization"] = {"status": "normalized", "at": datetime.now(timezone.utc).isoformat()}
            raw.raw_payload = payload
            session.commit()
        validate_offer.apply_async(args=[raw_id], queue="validation")
        return {"raw_id": raw_id, "status": "normalized"}
    finally:
        factory.kw["bind"].dispose()

@celery_app.task(bind=True, base=IngestionTask, name="app.workers.ingestion_tasks.validate_offer")
def validate_offer(self, raw_id: str):
    factory = make_session_factory()
    try:
        with factory() as session:
            raw = session.get(IngestionRaw, raw_id)
            if raw is None or raw.status not in {"pending", "unmatched"}:
                return {"raw_id": raw_id, "status": "skipped"}
            payload = raw.raw_payload or {}
            errors = []
            for field in ("store", "externalProductId", "brand", "fragrance", "title", "url", "availability", "capturedAt", "source"):
                if not str(payload.get(field) or "").strip():
                    errors.append(f"missing_{field}")
            if not str(payload.get("url") or "").startswith("https://"):
                errors.append("invalid_https_url")
            try:
                price = Decimal(str(payload.get("price")))
                if not price.is_finite() or price <= 0:
                    errors.append("invalid_price")
            except (InvalidOperation, TypeError, ValueError):
                errors.append("invalid_price")
            if not isinstance(payload.get("currency"), str) or len(payload["currency"]) != 3 or payload["currency"] != payload["currency"].upper():
                errors.append("invalid_currency")
            try:
                captured = datetime.fromisoformat(str(payload.get("capturedAt", "")).replace("Z", "+00:00"))
                if captured.tzinfo is None:
                    errors.append("captured_at_timezone_required")
            except (TypeError, ValueError):
                errors.append("invalid_captured_at")
            if payload.get("availability") not in {"in_stock", "out_of_stock", "preorder", "unknown"}:
                errors.append("invalid_availability")
            if errors:
                raw.status = "rejected"
                raw.rejection_reason = ",".join(errors)
                session.commit()
                return {"raw_id": raw_id, "status": "rejected", "errors": errors}
            session.commit()
        match_offer_to_variant.apply_async(args=[raw_id], queue="matching")
        return {"raw_id": raw_id, "status": "validated"}
    finally:
        factory.kw["bind"].dispose()

@celery_app.task(bind=True, base=IngestionTask, name="app.workers.ingestion_tasks.match_offer_to_variant")
def match_offer_to_variant(self, raw_id: str):
    factory = make_session_factory()
    try:
        with factory() as session:
            result = match_staged_offer(session, UUID(str(raw_id)))
            session.commit()
            status = result.status
        if status == "matched":
            promote_matched_offers_task.apply_async(queue="offers")
        return {"raw_id": raw_id, "status": status}
    except Exception:
        factory.kw["bind"].dispose()
        raise
    finally:
        factory.kw["bind"].dispose()


@celery_app.task(bind=True, base=IngestionTask, name="app.workers.ingestion_tasks.promote_matched_offers_task")
def promote_matched_offers_task(self, limit: int = 100):
    from app.workers.offer_promotion import promote_matched_offers
    return promote_matched_offers(make_session_factory, limit=limit)

def enqueue_product_detail_refresh(store_key: str, offer_id: str) -> str:
    """Queue a fresh price/stock check when a product detail is opened."""
    store_key = str(store_key or "").strip().lower()
    offer_id = str(offer_id or "").strip()
    if not store_key or not offer_id:
        raise ValueError("store_key_and_offer_id_required")
    result = refresh_price_and_stock.apply_async(
        kwargs={"store_key": store_key, "offer_id": offer_id},
        queue="refresh",
    )
    return str(result.id)


@celery_app.task(bind=True, base=IngestionTask, name="app.workers.ingestion_tasks.refresh_price_and_stock")
def refresh_price_and_stock(self, store_key: str, offer_id: str):
    factory = make_session_factory()
    try:
        with factory() as session:
            refreshable = session.execute(
                select(Offer.external_product_id, Offer.url)
                .join(Store, Offer.store_id == Store.id)
                .where(
                    Store.slug == store_key,
                    Store.status == "active",
                    Offer.status == "active",
                    Offer.external_product_id == offer_id,
                )
                .limit(1)
            ).first()
        if refreshable is None:
            return {"store": store_key, "offer_id": offer_id, "status": "not_refreshable"}
        external_product_id, product_url = refreshable
    finally:
        factory.kw["bind"].dispose()
    connector = get_connector(store_key)
    # Legacy connectors are recreated per Celery task, so their discovery
    # cache is empty during refresh. Load by the persisted product URL; the
    # parser still emits the stable external product ID for idempotent upsert.
    from app.connectors.legacy_store import LegacyStoreConnector
    refresh_key = product_url if isinstance(connector, LegacyStoreConnector) else external_product_id
    record = _run(connector.fetch_price_and_stock(refresh_key))
    raw_artifacts = list(getattr(connector, "_raw_artifacts", []) or [])
    artifact_ids = (
        _persist_raw_artifacts(store_key, None, raw_artifacts)
        if raw_artifacts else []
    )
    if record is None:
        return {
            "store": store_key, "offer_id": offer_id,
            "status": "not_refreshed", "raw_artifact_ids": artifact_ids,
        }
    raw_id = _stage_record(
        store_key, record,
        {"refresh_of": offer_id, "raw_artifact_ids": artifact_ids},
    )
    validate_offer.apply_async(args=[raw_id], queue="validation")
    return {
        "store": store_key, "offer_id": offer_id,
        "status": "refreshed", "raw_id": raw_id,
        "raw_artifact_ids": artifact_ids,
    }

@celery_app.task(bind=True, base=IngestionTask, name="app.workers.ingestion_tasks.quarantine_failed_connector")
def quarantine_failed_connector(self, store_key: str):
    factory = make_session_factory()
    try:
        with factory() as session:
            store = session.scalar(select(Store).where(Store.slug == store_key))
            if store is None:
                raise ValueError(f"unknown_store:{store_key}")
            recent = session.scalars(select(IngestionRun).where(
                IngestionRun.store_id == store.id
            ).order_by(IngestionRun.started_at.desc()).limit(QUARANTINE_AFTER)).all()
            consecutive = 0
            for run in recent:
                if run.status != "failed":
                    break
                consecutive += 1
            if consecutive >= QUARANTINE_AFTER:
                store.status = "quarantined"
            session.commit()
            return {"store": store_key, "consecutive_failures": consecutive, "status": store.status}
    finally:
        factory.kw["bind"].dispose()

@celery_app.task(bind=True, base=IngestionTask, name="app.workers.ingestion_tasks.reprocess_failed_offers")
def reprocess_failed_offers(self, store_key: str | None = None, limit: int = 100):
    if limit < 1 or limit > 5000:
        raise ValueError("limit_must_be_between_1_and_5000")
    factory = make_session_factory()
    try:
        with factory() as session:
            query = select(IngestionRaw).where(
                IngestionRaw.status == "rejected",
                IngestionRaw.rejection_reason.like("retryable:%"),
            ).order_by(IngestionRaw.created_at.asc()).limit(limit)
            rows = session.scalars(query).all()
            queued = []
            for row in rows:
                row.status = "pending"
                row.rejection_reason = None
                queued.append(str(row.id))
            session.commit()
        for raw_id in queued:
            normalize_offer.apply_async(args=[raw_id], queue="validation")
        return {"requeued": len(queued), "raw_ids": queued}
    finally:
        factory.kw["bind"].dispose()

@celery_app.task(name="app.workers.ingestion_tasks.record_dead_letter")
def record_dead_letter(task_name: str, task_id: str, args_repr: str, kwargs_repr: str, error: str):
    factory = make_session_factory()
    try:
        with factory() as session:
            row = session.scalar(select(IngestionDeadLetter).where(IngestionDeadLetter.task_id == task_id))
            if row is None:
                row = IngestionDeadLetter(
                    task_name=task_name,
                    task_id=task_id,
                    args_repr=args_repr[:4000],
                    kwargs_repr=kwargs_repr[:4000],
                    error=error[:2000],
                    status="open",
                )
                session.add(row)
            else:
                row.error = error[:2000]
                row.status = "open"
            session.commit()
        logger.error("DEAD_LETTER task=%s id=%s error=%s", task_name, task_id, error)
        return {"recorded": True, "task_id": task_id}
    finally:
        factory.kw["bind"].dispose()

def _configured_store_keys():
    """Schedule only connectors whose Phase 2 store row is explicitly active."""
    connector_keys = set(build_connectors().keys())
    factory = make_session_factory()
    try:
        with factory() as session:
            active_store_keys = set(session.scalars(
                select(Store.slug).where(Store.status == "active")
            ).all())
        return sorted(connector_keys & active_store_keys)
    finally:
        factory.kw["bind"].dispose()

@celery_app.task(name="app.workers.ingestion_tasks.enqueue_discovery_for_configured_stores")
def enqueue_discovery_for_configured_stores():
    keys = _configured_store_keys()
    for key in keys:
        discover_store_products.apply_async(args=[key], queue="discovery")
    return {"queued_stores": keys}

@celery_app.task(name="app.workers.ingestion_tasks.enqueue_offer_collection_for_configured_stores")
def enqueue_offer_collection_for_configured_stores():
    """Refresh all known active offers without repeating product discovery."""
    factory = make_session_factory()
    try:
        with factory() as session:
            rows = session.execute(
                select(Offer.external_product_id, Store.slug)
                .join(Store, Offer.store_id == Store.id)
                .where(
                    Store.status == "active",
                    Offer.status == "active",
                    Offer.external_product_id.is_not(None),
                )
                .order_by(Store.slug.asc(), Offer.external_product_id.asc())
            ).all()
            queued = 0
            seen = set()
            for external_product_id, store_key in rows:
                key = (store_key, external_product_id)
                if key in seen:
                    continue
                seen.add(key)
                refresh_price_and_stock.apply_async(
                    kwargs={"store_key": store_key, "offer_id": external_product_id},
                    queue="refresh",
                )
                queued += 1
        return {"refresh_jobs_queued": queued, "stores": sorted({key[0] for key in seen})}
    finally:
        factory.kw["bind"].dispose()

@celery_app.task(name="app.workers.ingestion_tasks.enqueue_refresh_for_active_stores")
def enqueue_refresh_for_active_stores():
    factory = make_session_factory()
    try:
        with factory() as session:
            import os
            main_stores = {
                item.strip() for item in os.environ.get("SCENTHUNTER_MAIN_REFRESH_STORES", "").split(",")
                if item.strip()
            }
            if not main_stores:
                return {"refresh_jobs_queued": 0, "note": "Set SCENTHUNTER_MAIN_REFRESH_STORES to opt stores into the 30-minute refresh cadence"}
            rows = session.execute(
                select(Offer.external_product_id, Store.slug)
                .join(Store, Offer.store_id == Store.id)
                .where(Store.status == "active", Offer.status == "active",
                       Offer.external_product_id.is_not(None), Store.slug.in_(main_stores))
            ).all()
            queued = 0
            for external_product_id, store_key in rows:
                refresh_price_and_stock.apply_async(
                    kwargs={"store_key": store_key, "offer_id": external_product_id},
                    queue="refresh",
                )
                queued += 1
        return {"refresh_jobs_queued": queued}
    finally:
        factory.kw["bind"].dispose()


@celery_app.task(name="app.workers.ingestion_tasks.staging_worker_smoke")
def staging_worker_smoke(probe: str = "phase5"):
    """Side-effect-free staging probe proving a queued task executed on a worker."""
    from celery import current_task
    return {
        "ok": True,
        "probe": str(probe)[:80],
        "task_id": current_task.request.id,
        "worker": current_task.request.hostname,
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }
