"""Legacy synchronous ingestion compatibility runner.

Production ingestion is owned by ingestion_tasks.discover_store_products,
which stages raw evidence and queues the canonical normalize/validate/match/
promote pipeline. This adapter remains for isolated fixtures and compatibility;
it must not be scheduled as a production ingestion worker.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select

from app.connectors.base import StoreConnector, validate_offer_payload
from app.models import IngestionRaw, IngestionRun, Store


def run_connector_once(
    connector: StoreConnector,
    session_factory: Callable,
    *,
    quarantine_after: int = 3,
) -> dict:
    """Discover and stage one store's offers in an isolated DB transaction.

    Invalid evidence is retained with status=rejected. Valid evidence remains
    pending for later matching. Repeated consecutive connector failures set
    only that store to quarantined; no offer is published here.
    """
    if quarantine_after < 1:
        raise ValueError("quarantine_after_must_be_positive")

    session = session_factory()
    run_id = None
    try:
        store = session.scalar(select(Store).where(Store.slug == connector.store_key))
        if store is None:
            raise ValueError(f"connector_store_not_configured:{connector.store_key}")
        if store.status == "quarantined":
            return {"store": connector.store_key, "status": "quarantined", "staged": 0}

        run = IngestionRun(store_id=store.id, status="running", errors=[])
        session.add(run)
        session.flush()
        run_id = run.id
        session.commit()
    finally:
        session.close()

    async def collect():
        discovered = await connector.discover_products()
        records = []
        seen = set()
        for product in discovered:
            product_key = str(
                product.get("externalProductId")
                or product.get("external_product_id")
                or product.get("url")
                or ""
            ).strip()
            if not product_key or product_key in seen:
                continue
            seen.add(product_key)
            records.extend(await connector.fetch_offers(product_key))
        return len(discovered), records

    try:
        import asyncio
        discovered_count, records = asyncio.run(collect())
        session = session_factory()
        try:
            run = session.get(IngestionRun, run_id)
            if run is None:
                raise LookupError("ingestion_run_not_found_after_collection")
            store = session.get(Store, run.store_id)
            staged = rejected = 0
            for record in records:
                payload = record.to_dict()
                valid, errors = validate_offer_payload(payload)
                errors = list(errors)
                payload_store = str(payload.get("store") or "").strip().lower()
                if payload_store != str(store.slug or "").strip().lower():
                    errors.append("store_attribution_mismatch")
                raw = IngestionRaw(
                    store_id=store.id,
                    raw_payload=payload,
                    external_product_id=record.external_product_id,
                    status="pending" if valid and not errors else "rejected",
                    rejection_reason=None if valid and not errors else ",".join(errors),
                )
                session.add(raw)
                staged += 1
                rejected += int(not valid or bool(errors))
            run.products_discovered = discovered_count
            run.offers_created = 0
            run.offers_updated = 0
            run.offers_rejected = rejected
            run.status = "completed"
            run.finished_at = datetime.now(timezone.utc)
            # A successful run resets consecutive failure history.
            store.last_successful_sync_at = run.finished_at
            session.commit()
            return {
                "store": connector.store_key,
                "status": "completed",
                "discovered": discovered_count,
                "staged": staged,
                "rejected": rejected,
                "published": 0,
            }
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    except Exception as exc:
        session = session_factory()
        try:
            run = session.get(IngestionRun, run_id)
            if run is None:
                raise LookupError("ingestion_run_not_found_while_recording_failure")
            store = session.get(Store, run.store_id)
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.errors = [{"type": type(exc).__name__, "message": str(exc)[:500]}]
            # Count only the immediately preceding failed runs for this store.
            recent = session.scalars(
                select(IngestionRun)
                .where(IngestionRun.store_id == store.id)
                .order_by(IngestionRun.started_at.desc())
                .limit(quarantine_after)
            ).all()
            consecutive = 0
            for previous in recent:
                if previous.status != "failed":
                    break
                consecutive += 1
            if consecutive >= quarantine_after:
                store.status = "quarantined"
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        return {
            "store": connector.store_key,
            "status": "quarantined" if consecutive >= quarantine_after else "failed",
            "error": type(exc).__name__,
            "published": 0,
        }
