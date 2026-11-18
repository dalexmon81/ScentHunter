"""Stream the authorized Notino CJ feed and persist the first safe canonical match."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.notino_feed import NotinoAffiliateFeedConnector
from app.db import make_engine
from app.models import IngestionRaw, IngestionRun, Offer, Store
from app.services.connector_ingestion import persist_connector_record
from scrapers.notino import affiliate_feed
from scenthunter_next_engine.next_engine_service import NextEngineService
from scenthunter_next_engine.offer_normalizer import normalize_offer

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"


def _eligible(record: dict) -> bool:
    try:
        size = Decimal(str(record.get("size_ml") or "0"))
        price = Decimal(str(record.get("price") or "0"))
    except Exception:
        return False
    return (
        size > 0
        and price > 0
        and bool(record.get("brand"))
        and bool(record.get("title"))
        and record.get("currency_explicit") is True
        and record.get("availability") in {"in_stock", "out_of_stock"}
        and bool(record.get("product_url") or record.get("url"))
        and not bool(record.get("is_tester"))
        and not bool(record.get("is_refill"))
        and not bool(record.get("is_gift_set"))
    )


def main() -> int:
    print("NOTINO_SMOKE_START=1", flush=True)
    required = ("NOTINO_CJ_FEED_USERNAME", "NOTINO_CJ_FEED_PASSWORD")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SystemExit("NOTINO_CJ_FEED_CREDENTIALS_MISSING=" + ",".join(missing))
    if not CATALOG_PATH.is_file():
        raise SystemExit("CANONICAL_MATCHER_CATALOG_MISSING")

    connector = NotinoAffiliateFeedConnector(cache_ttl_seconds=900)
    print("NOTINO_CONNECTOR_READY=1", flush=True)
    matcher = NextEngineService.from_catalog_file(CATALOG_PATH)
    print("NOTINO_MATCHER_READY=1", flush=True)
    engine = make_engine()
    try:
        with Session(engine) as session:
            store = session.scalar(select(Store).where(Store.slug == "notino-fr"))
            if store is None or store.status != "active":
                raise SystemExit("NOTINO_CANONICAL_STORE_NOT_ACTIVE")
            store_id = store.id
        print("NOTINO_STORE_READY=1", flush=True)

        downloaded_bytes = 0
        scanned = 0
        eligible = 0
        stats: dict = {}
        match_diagnostics: list[dict] = []
        print("NOTINO_CJ_FEED_DOWNLOAD_STARTED=1", flush=True)
        with tempfile.TemporaryFile(mode="w+b") as payload:
            downloaded_bytes = affiliate_feed._download_feed(payload)
            print("NOTINO_CJ_FEED_BYTES=" + str(downloaded_bytes), flush=True)
            payload.seek(0)
            with affiliate_feed._xml_stream(payload) as stream:
                for feed_offer in affiliate_feed._parsed_offers(stream, stats):
                    scanned += 1
                    if scanned % 5000 == 0:
                        print("NOTINO_CJ_FEED_SCANNED=" + str(scanned), flush=True)
                    record = connector._to_record(feed_offer)
                    title_lower = str(record.get("title") or "").casefold()
                    gtin = str(record.get("gtin") or "").strip()
                    if (
                        ("liquid brun" in title_lower or gtin == "6298042001831")
                        and len(match_diagnostics) < 20
                    ):
                        diagnostic_parsed = connector.parse_raw(record)
                        diagnostic_offer = normalize_offer(
                            diagnostic_parsed, retailer=connector.store_key
                        )
                        diagnostic_result = matcher.process_offers([diagnostic_offer])
                        match_diagnostics.append({
                            "title": record.get("title"),
                            "brand": record.get("brand"),
                            "size_ml": record.get("size_ml"),
                            "gtin": gtin or None,
                            "concentration": record.get("concentration"),
                            "price": record.get("price"),
                            "currency": record.get("currency"),
                            "availability": record.get("availability"),
                            "eligible": _eligible(record),
                            "normalized_gtin": diagnostic_offer.raw_payload.get("gtin"),
                            "matched": diagnostic_result.matched_offer_count,
                            "groups": [
                                {
                                    "product_id": group.canonical_product_id,
                                    "variant_id": group.canonical_variant_id,
                                }
                                for group in diagnostic_result.groups
                            ],
                            "unresolved": [
                                item.reason or item.status.value
                                for item in diagnostic_result.unresolved
                            ],
                            "ambiguous": [
                                item.reason or item.status.value
                                for item in diagnostic_result.ambiguous
                            ],
                        })
                    if not _eligible(record):
                        continue
                    eligible += 1
                    parsed = connector.parse_raw(record)
                    normalized = normalize_offer(parsed, retailer=connector.store_key)
                    aggregation = matcher.process_offers([normalized])
                    if (
                        aggregation.input_count != 1
                        or aggregation.matched_offer_count != 1
                        or len(aggregation.groups) != 1
                        or len(aggregation.groups[0].offers) != 1
                        or not getattr(aggregation.groups[0], "canonical_variant_id", None)
                    ):
                        continue

                    with Session(engine) as session, session.begin():
                        existing = session.scalar(
                            select(Offer.id).where(
                                Offer.store_id == store_id,
                                Offer.external_product_id == str(record["external_product_id"]),
                            ).limit(1)
                        )
                        run = IngestionRun(
                            store_id=store_id,
                            status="running",
                            products_discovered=1,
                        )
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

                        print("NOTINO_CJ_FEED_DOWNLOAD=PASS", flush=True)
                        print("NOTINO_CJ_FEED_RECORDS_SCANNED=" + str(scanned), flush=True)
                        print("NOTINO_CJ_FEED_ELIGIBLE_RECORDS=" + str(eligible), flush=True)
                        print("NOTINO_CANONICAL_MATCH=PASS", flush=True)
                        print("NOTINO_OFFER_PERSISTENCE=PASS", flush=True)
                        print("NOTINO_OFFER_ID=" + str(offer.id), flush=True)
                        print("NOTINO_VARIANT_ID=" + str(offer.product_variant_id), flush=True)
                        print("NOTINO_PRICE=" + str(offer.price) + " " + offer.currency, flush=True)
                        print("NOTINO_AVAILABILITY=" + str(offer.availability), flush=True)
                        print("NOTINO_OFFER_STATUS=" + str(offer.status), flush=True)
                        return 0


        print("NOTINO_MATCH_DIAGNOSTICS=" + json.dumps(match_diagnostics, ensure_ascii=False), flush=True)
        raise SystemExit(
            "NOTINO_CJ_FEED_DOWNLOADED_BYTES=" + str(downloaded_bytes)
            + "; RECORDS_SCANNED=" + str(scanned)
            + "; ELIGIBLE_RECORDS=" + str(eligible)
            + "; NO_UNIQUE_CANONICAL_VARIANT_PROMOTED"
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
