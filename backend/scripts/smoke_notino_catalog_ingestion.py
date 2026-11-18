"""Verify one real authorized Notino CJ feed item through canonical persistence.

This is an explicit, bounded pilot smoke test. It never imports the whole feed
into the legacy catalog and only writes an offer after the canonical matcher
resolves a single existing product variant.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.notino_feed import NotinoAffiliateFeedConnector
from app.db import make_engine
from app.models import IngestionRaw, IngestionRun, Offer, Store
from app.services.connector_ingestion import persist_connector_record
from scenthunter_next_engine.next_engine_service import NextEngineService
from scenthunter_next_engine.offer_normalizer import normalize_offer

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"


def _target_record(record: dict) -> bool:
    title = str(record.get("title") or "").lower()
    brand = str(record.get("brand") or "").lower()
    try:
        size = float(record.get("size_ml") or 0)
        price = Decimal(str(record.get("price") or "0"))
    except Exception:
        return False
    if size != 100 or price <= 0:
        return False
    if record.get("currency_explicit") is not True:
        return False
    if record.get("availability") not in {"in_stock", "out_of_stock"}:
        return False
    liquid_brun = "liquid brun" in title and "french avenue" in brand
    sauvage = "sauvage" in title and "dior" in brand and "eau de parfum" in title
    return liquid_brun or sauvage


def main() -> int:
    required = (
        "NOTINO_CJ_FEED_USERNAME",
        "NOTINO_CJ_FEED_PASSWORD",
    )
    import os
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SystemExit("NOTINO_CJ_FEED_CREDENTIALS_MISSING=" + ",".join(missing))
    if not CATALOG_PATH.is_file():
        raise SystemExit("CANONICAL_MATCHER_CATALOG_MISSING")

    connector = NotinoAffiliateFeedConnector(cache_ttl_seconds=900)
    count = asyncio.run(connector.refresh_snapshot())
    snapshot = asyncio.run(connector._get_snapshot())
    candidates = [row for row in snapshot if _target_record(row)]
    if not candidates:
        raise SystemExit(
            f"NOTINO_CJ_FEED_DOWNLOADED={count}; "
            "NO_IN_STOCK_OR_VALID_100ML_LIQUID_BRUN_OR_DIOR_SAUVAGE_CANDIDATE"
        )

    matcher = NextEngineService.from_catalog_file(CATALOG_PATH)
    engine = make_engine()
    try:
        with Session(engine) as session:
            store = session.scalar(select(Store).where(Store.slug == "notino-fr"))
            if store is None or store.status != "active":
                raise SystemExit("NOTINO_CANONICAL_STORE_NOT_ACTIVE")
            store_id = store.id

        last_reason = None
        for record in candidates:
            parsed = connector.parse_raw(record)
            normalized = normalize_offer(parsed, retailer=connector.store_key)
            aggregation = matcher.process_offers([normalized])
            if (
                aggregation.input_count != 1
                or aggregation.matched_offer_count != 1
                or len(aggregation.groups) != 1
                or len(aggregation.groups[0].offers) != 1
            ):
                last_reason = "canonical_match_not_unique"
                continue

            with Session(engine) as session, session.begin():
                store = session.get(Store, store_id)
                existing = session.scalar(
                    select(Offer.id).where(
                        Offer.store_id == store_id,
                        Offer.external_product_id == str(record["external_product_id"]),
                    ).limit(1)
                )
                run = IngestionRun(store_id=store_id, status="running", products_discovered=1)
                session.add(run)
                session.flush()
                result = persist_connector_record(
                    session,
                    connector=connector,
                    store_id=store_id,
                    raw_record=dict(record),
                    matcher=matcher,
                )
                if result.status != "promoted" or result.offer_id is None:
                    run.offers_rejected = 1
                    run.errors = [str(result.reason or result.status)]
                    run.status = "partial"
                    run.finished_at = datetime.now(timezone.utc)
                    last_reason = result.reason or result.status
                    continue

                offer = session.get(Offer, result.offer_id)
                raw = session.get(IngestionRaw, result.ingestion_raw_id)
                if (
                    offer is None
                    or raw is None
                    or raw.status != "promoted"
                    or offer.status != "active"
                    or offer.product_variant_id != result.product_variant_id
                ):
                    raise RuntimeError("NOTINO_PERSISTED_OFFER_VERIFICATION_FAILED")

                run.offers_created = 0 if existing else 1
                run.offers_updated = 1 if existing else 0
                run.status = "completed"
                run.finished_at = datetime.now(timezone.utc)

                print("NOTINO_CJ_FEED_DOWNLOAD=PASS")
                print("NOTINO_CJ_FEED_RECORDS=" + str(count))
                print("NOTINO_CANONICAL_MATCH=PASS")
                print("NOTINO_OFFER_PERSISTENCE=PASS")
                print("NOTINO_OFFER_ID=" + str(offer.id))
                print("NOTINO_VARIANT_ID=" + str(offer.product_variant_id))
                print("NOTINO_PRICE=" + str(offer.price) + " " + offer.currency)
                print("NOTINO_AVAILABILITY=" + str(offer.availability))
                print("NOTINO_OFFER_STATUS=" + str(offer.status))
                return 0

        raise SystemExit(
            "NOTINO_CJ_FEED_DOWNLOADED="
            + str(count)
            + "; NO_SAFE_CANONICAL_OFFER_PROMOTED; reason="
            + str(last_reason or "no_unique_match")
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
