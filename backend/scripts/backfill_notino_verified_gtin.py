"""Dry-run/apply promotion of Notino Dior Sauvage EDP rows with reviewed exact GTINs.

Only the four explicitly reviewed GTINs are eligible. Dry-run is the default.
The script never broadens matching beyond exact GTIN-to-canonical-variant identity.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import make_engine
from app.models import IngestionRaw, Offer, Store
from app.search.catalog import _offer_url_valid
from app.services.ingestion_persistence import record_legacy_match, promote_offer
from scenthunter_next_engine.canonical_matcher import CanonicalMatcher
from scenthunter_next_engine.catalog_repository import CatalogRepository
from scenthunter_next_engine.offer_normalizer import normalize_offer


VERIFIED_GTINS = {
    "3348901608053": {
        "variant_id": "VAR-SH-AUTO-0178-EDP-30",
        "size_ml": 30,
        "path": "/dior/sauvage-eau-de-parfum-pour-homme/p-16187295/",
    },
    "3348901368254": {
        "variant_id": "VAR-SH-AUTO-0178-EDP-60",
        "size_ml": 60,
        "path": "/dior/sauvage-eau-de-parfum-pour-homme/p-15676582/",
    },
    "3348901368247": {
        "variant_id": "VAR-SH-AUTO-0178-EDP-100",
        "size_ml": 100,
        "path": "/dior/sauvage-eau-de-parfum-pour-homme/p-15676518/",
    },
    "3348901428545": {
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


def backfill_verified_notino_gtins(
    session: Session,
    store: Store,
    *,
    catalog_path: str | Path,
    apply: bool = False,
) -> dict:
    catalog = CatalogRepository.from_file(catalog_path)
    matcher = CanonicalMatcher(catalog)
    rows = session.scalars(
        select(IngestionRaw)
        .where(
            IngestionRaw.store_id == store.id,
            IngestionRaw.status.in_(("pending", "unmatched")),
        )
        .order_by(IngestionRaw.created_at.desc(), IngestionRaw.id.desc())
    ).all()

    latest_by_gtin = {}
    seen_gtins = set()
    skipped = Counter()
    duplicate_rows = 0
    for row in rows:
        payload = row.raw_payload if isinstance(row.raw_payload, dict) else {}
        gtin = str(payload.get("gtin") or payload.get("gtin13") or "").strip()
        if gtin not in VERIFIED_GTINS:
            continue
        if gtin in seen_gtins:
            duplicate_rows += 1
            continue
        seen_gtins.add(gtin)

        try:
            offer = normalize_offer(payload, retailer="Notino", currency_default="EUR")
            matched = matcher.match(offer)
        except (TypeError, ValueError):
            skipped["normalization_failed"] += 1
            continue

        expected = VERIFIED_GTINS[gtin]
        # The matcher may select its exact name/brand/size path before its
        # GTIN path. The reviewed registry remains authoritative: require a
        # valid GTIN checksum plus the exact expected canonical variant ID.
        if not _valid_gtin13(gtin):
            skipped["invalid_gtin_checksum"] += 1
            continue
        if matched.canonical_product_id != CANONICAL_PRODUCT_ID:
            skipped["unexpected_canonical_product"] += 1
            continue
        if matched.canonical_variant_id != expected["variant_id"]:
            skipped["unexpected_canonical_variant"] += 1
            continue
        if offer.size_ml != expected["size_ml"]:
            skipped["explicit_size_mismatch"] += 1
            continue
        if payload.get("currency_explicit") is not True:
            skipped["currency_not_explicit"] += 1
            continue
        if offer.currency != "EUR":
            skipped["currency_not_eur"] += 1
            continue
        if offer.price is None or offer.price <= 0:
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

        existing = session.scalar(
            select(Offer).where(
                Offer.store_id == store.id,
                Offer.external_product_id == row.external_product_id,
                Offer.status == "active",
            )
        )
        if existing is not None and existing.availability == "in_stock":
            skipped["already_active_in_stock_offer"] += 1
            continue

        latest_by_gtin[gtin] = {
            "row": row,
            "payload": payload,
            "offer": offer,
            "match": matched,
        }

    summary = {
        "mode": "apply" if apply else "dry_run",
        "store": store.slug,
        "pending_rows_scanned": len(rows),
        "verified_gtin_candidates": len(latest_by_gtin),
        "duplicate_rows_suppressed": duplicate_rows,
        "skipped_reasons": dict(sorted(skipped.items())),
        "candidates": [
            {
                "raw_id": str(item["row"].id),
                "external_product_id": item["row"].external_product_id,
                "gtin": gtin,
                "product_id": item["match"].canonical_product_id,
                "variant_id": item["match"].canonical_variant_id,
                "size_ml": item["offer"].size_ml,
                "price": str(item["offer"].price),
                "currency": item["offer"].currency,
                "availability": item["offer"].availability,
                "url_host": urlparse(item["offer"].product_url or "").hostname,
            }
            for gtin, item in sorted(latest_by_gtin.items())
        ],
        "database_written": False,
    }

    if apply:
        promoted = 0
        with session.begin_nested():
            for gtin, item in sorted(latest_by_gtin.items()):
                row = item["row"]
                offer = item["offer"]
                matched = item["match"]
                payload = dict(item["payload"])
                payload["verified_gtin_backfill"] = {
                    "gtin": gtin,
                    "product_id": matched.canonical_product_id,
                    "variant_id": matched.canonical_variant_id,
                    "method": "notino_reviewed_verified_gtin_registry",
                }
                row.raw_payload = payload
                resolved = record_legacy_match(
                    session,
                    ingestion_raw_id=row.id,
                    legacy_product_id=matched.canonical_product_id,
                    legacy_variant_id=matched.canonical_variant_id,
                    method="notino_reviewed_verified_gtin_registry",
                    confidence=matched.confidence,
                )
                if resolved is None:
                    raise RuntimeError(f"Canonical DB mapping missing for GTIN {gtin}")
                promote_offer(
                    session,
                    ingestion_raw_id=row.id,
                    price=offer.price,
                    currency=offer.currency,
                    url=offer.product_url,
                    availability=offer.availability,
                    source="notino_reviewed_verified_gtin_registry",
                    confidence=matched.confidence,
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
                session.commit()
            print("NOTINO_VERIFIED_GTIN_BACKFILL=" + json.dumps(
                summary, ensure_ascii=False, sort_keys=True,
            ))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
