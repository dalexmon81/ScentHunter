"""Targeted, fresh-feed promotion of four reviewed Notino Dior Sauvage EDP GTINs.

Dry-run is the default. Apply mode fetches the current authorized CJ/VIV feed
snapshot and promotes only the four exact GTIN/external-ID/variant/URL pairs.
It never scans the whole Notino feed or stamps an old staged payload as fresh.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import make_engine
from app.models import IngestionRaw, Offer, Store
from app.search.catalog import _offer_url_valid
from app.services.ingestion_persistence import (
    promote_offer,
    record_legacy_match,
    stage_raw_offer,
)
from scenthunter_next_engine.catalog_repository import CatalogRepository
from scenthunter_next_engine.offer_normalizer import normalize_offer
from app.connectors.notino_feed import NotinoAffiliateFeedConnector


VERIFIED_GTINS = {
    "3348901608053": {
        "external_product_id": "CHDSVGM_AEDP40",
        "variant_id": "VAR-SH-AUTO-0178-EDP-30",
        "size_ml": 30,
        "path": "/dior/sauvage-eau-de-parfum-pour-homme/p-16187295/",
    },
    "3348901368254": {
        "external_product_id": "CHDSVGM_AEDP20",
        "variant_id": "VAR-SH-AUTO-0178-EDP-60",
        "size_ml": 60,
        "path": "/dior/sauvage-eau-de-parfum-pour-homme/p-15676582/",
    },
    "3348901368247": {
        "external_product_id": "CHDSVGM_AEDP10",
        "variant_id": "VAR-SH-AUTO-0178-EDP-100",
        "size_ml": 100,
        "path": "/dior/sauvage-eau-de-parfum-pour-homme/p-15676518/",
    },
    "3348901428545": {
        "external_product_id": "CHDSVGM_AEDP25",
        "variant_id": "VAR-SH-AUTO-0178-EDP-200",
        "size_ml": 200,
        "path": "/dior/sauvage-eau-de-parfum-pour-homme/p-15971107/",
    },
}
CANONICAL_PRODUCT_ID = "SH-AUTO-0178"


def _valid_gtin13(value: str) -> bool:
    if len(value) != 13 or not value.isdigit():
        return False
    weighted_sum = sum(
        int(digit) * (1 if index % 2 == 0 else 3)
        for index, digit in enumerate(value[:12])
    )
    return (10 - weighted_sum % 10) % 10 == int(value[-1])


def _payload_identity_matches(payload: dict, expected: dict) -> bool:
    title = str(payload.get("title") or "").casefold()
    brand = str(payload.get("brand") or "").strip().casefold()
    concentration = str(payload.get("concentration") or "").casefold()
    try:
        size_ml = int(payload.get("size_ml") or 0)
    except (TypeError, ValueError):
        return False
    return (
        brand == "dior"
        and "sauvage" in title
        and "eau de parfum" in title
        and "eau de parfum" in concentration
        and size_ml == int(expected["size_ml"])
    )


async def _fetch_current_feed_records(connector) -> dict[str, dict]:
    """Fetch only the four reviewed IDs from one freshly loaded feed snapshot."""
    records = {}
    for gtin, expected in VERIFIED_GTINS.items():
        external_id = expected["external_product_id"]
        raw = await connector.fetch_product(external_id)
        if not isinstance(raw, dict):
            continue
        if str(raw.get("external_product_id") or "") != external_id:
            continue
        if str(raw.get("gtin") or "") != gtin:
            continue
        records[gtin] = dict(raw)
    return records


def backfill_verified_notino_gtins(
    session: Session,
    store: Store,
    *,
    catalog_path: str | Path,
    apply: bool = False,
    feed_connector=None,
    feed_records: dict[str, dict] | None = None,
) -> dict:
    if store.slug != "notino-fr" or store.status != "active":
        raise ValueError("Notino store must be active before the verified GTIN backfill")

    # One connector instance and one event loop mean one current feed download,
    # then four indexed lookups. No full-feed pagination or fetch-job fan-out.
    if feed_records is None:
        connector = feed_connector or NotinoAffiliateFeedConnector()
        records = asyncio.run(_fetch_current_feed_records(connector))
    else:
        # Production bootstrap fetches the remote feed before opening a DB transaction.
        records = feed_records
    # Validate every reviewed legacy variant ID and size against the deployed catalog.
    catalog = CatalogRepository.from_file(catalog_path)
    canonical_product = catalog.get(CANONICAL_PRODUCT_ID)
    if canonical_product is None:
        raise RuntimeError("Reviewed Dior Sauvage canonical product is missing from catalog")
    catalog_variants = {variant.variant_id: variant.size_ml for variant in canonical_product.variants}
    for expected in VERIFIED_GTINS.values():
        if catalog_variants.get(expected["variant_id"]) != expected["size_ml"]:
            raise RuntimeError(
                "Reviewed GTIN registry does not match the canonical catalog variant sizes"
            )

    candidates = {}
    skipped = Counter()
    for gtin, expected in VERIFIED_GTINS.items():
        payload = records.get(gtin)
        if payload is None:
            skipped["gtin_missing_from_current_feed_snapshot"] += 1
            continue
        if not _valid_gtin13(gtin):
            skipped["invalid_gtin_checksum"] += 1
            continue
        if payload.get("currency_explicit") is not True:
            skipped["currency_not_explicit"] += 1
            continue
        if str(payload.get("currency") or "").upper() != "EUR":
            skipped["currency_not_eur"] += 1
            continue
        if str(payload.get("source") or "") != "authorized_cj_viv_xml_feed":
            skipped["source_not_authorized_feed"] += 1
            continue

        if not _payload_identity_matches(payload, expected):
            skipped["brand_concentration_or_size_identity_mismatch"] += 1
            continue

        try:
            offer = normalize_offer(payload, retailer="Notino", currency_default="EUR")
        except (TypeError, ValueError):
            skipped["normalization_failed"] += 1
            continue
        if offer.size_ml != expected["size_ml"]:
            skipped["explicit_size_mismatch"] += 1
            continue
        if offer.price is None or not isinstance(offer.price, Decimal) or offer.price <= 0:
            skipped["invalid_price"] += 1
            continue
        if offer.availability not in {"in_stock", "out_of_stock"}:
            skipped["availability_not_explicit"] += 1
            continue
        parsed = urlparse(offer.product_url or "")
        if parsed.path != expected["path"]:
            skipped["product_url_path_mismatch"] += 1
            continue
        if not _offer_url_valid(offer.product_url, store.domain):
            skipped["invalid_store_url"] += 1
            continue

        candidates[gtin] = {
            "payload": payload,
            "offer": offer,
            "expected": expected,
        }

    summary = {
        "mode": "apply" if apply else "dry_run",
        "store": store.slug,
        "source": "current_authorized_cj_viv_xml_feed",
        "gtin_candidates": len(candidates),
        "expected_gtins": len(VERIFIED_GTINS),
        "skipped_reasons": dict(sorted(skipped.items())),
        "candidates": [
            {
                "external_product_id": item["expected"]["external_product_id"],
                "gtin": gtin,
                "product_id": CANONICAL_PRODUCT_ID,
                "variant_id": item["expected"]["variant_id"],
                "size_ml": item["offer"].size_ml,
                "price": str(item["offer"].price),
                "currency": item["offer"].currency,
                "availability": item["offer"].availability,
                "url_host": urlparse(item["offer"].product_url or "").hostname,
                "url_path": urlparse(item["offer"].product_url or "").path,
            }
            for gtin, item in sorted(candidates.items())
        ],
        "promoted_unique_gtins": 0,
        "database_written": False,
    }

    # Atomic all-four gate: never partially publish the reviewed pilot.
    if not apply or len(candidates) != len(VERIFIED_GTINS):
        return summary

    promoted = 0
    with session.begin_nested():
        for gtin, item in sorted(candidates.items()):
            expected = item["expected"]
            payload = dict(item["payload"])
            offer = item["offer"]
            external_id = expected["external_product_id"]

            row = session.scalar(
                select(IngestionRaw)
                .where(
                    IngestionRaw.store_id == store.id,
                    IngestionRaw.external_product_id == external_id,
                    IngestionRaw.status.in_(("pending", "unmatched")),
                )
                .order_by(IngestionRaw.created_at.desc(), IngestionRaw.id.desc())
                .limit(1)
            )
            if row is None:
                raw_id = stage_raw_offer(
                    session,
                    store_id=store.id,
                    raw_payload=payload,
                    external_product_id=external_id,
                )
                row = session.get(IngestionRaw, raw_id)
            else:
                row.raw_payload = payload
                row.updated_at = datetime.now(timezone.utc)

            payload["verified_gtin_backfill"] = {
                "gtin": gtin,
                "product_id": CANONICAL_PRODUCT_ID,
                "variant_id": expected["variant_id"],
                "method": "notino_reviewed_verified_gtin_current_feed",
            }
            row.raw_payload = payload

            resolved = record_legacy_match(
                session,
                ingestion_raw_id=row.id,
                legacy_product_id=CANONICAL_PRODUCT_ID,
                legacy_variant_id=expected["variant_id"],
                method="notino_reviewed_verified_gtin_current_feed",
                confidence=Decimal("1.0"),
            )
            if resolved is None:
                raise RuntimeError(f"Canonical DB mapping missing for GTIN {gtin}")

            existing = session.scalar(
                select(Offer).where(
                    Offer.store_id == store.id,
                    Offer.external_product_id == external_id,
                ).order_by(Offer.captured_at.desc()).limit(1)
            )
            if existing is not None and existing.product_variant_id != resolved.product_variant_id:
                raise RuntimeError(
                    f"Existing Notino offer identity conflicts with reviewed GTIN {gtin}"
                )

            promote_offer(
                session,
                ingestion_raw_id=row.id,
                price=offer.price,
                currency=offer.currency,
                url=offer.product_url,
                availability=offer.availability,
                source="notino_reviewed_verified_gtin_current_feed",
                confidence=Decimal("1.0"),
            )
            promoted += 1

    session.flush()
    summary["promoted_unique_gtins"] = promoted
    summary["database_written"] = True
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="persist the four reviewed exact-GTIN matches")
    parser.add_argument("--catalog", default="/app/backend/product_catalog.json")
    args = parser.parse_args()

    engine = make_engine()
    try:
        with Session(engine) as session:
            store = session.scalar(select(Store).where(Store.slug == "notino-fr"))
            if store is None or store.status != "active":
                raise SystemExit("NOTINO_STORE_NOT_ACTIVE")
            summary = backfill_verified_notino_gtins(
                session, store, catalog_path=args.catalog, apply=args.apply,
            )
            if args.apply:
                if summary["promoted_unique_gtins"] != len(VERIFIED_GTINS):
                    raise SystemExit(
                        "NOTINO_VERIFIED_GTIN_BACKFILL_INCOMPLETE="
                        + json.dumps(summary, ensure_ascii=False, sort_keys=True)
                    )
                session.commit()
            print("NOTINO_VERIFIED_GTIN_BACKFILL=" + json.dumps(
                summary, ensure_ascii=False, sort_keys=True,
            ))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
