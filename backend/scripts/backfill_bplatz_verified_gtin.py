"""Dry-run/apply backfill for Bplatz rows with reviewed, exact GTIN mappings.

Dry-run is the default. Apply promotes at most one latest row per verified GTIN,
and only when size, currency evidence, price, availability and store URL all pass.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from decimal import Decimal
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import make_engine
from app.models import IngestionRaw, Store
from app.search.catalog import _offer_url_valid
from app.services.ingestion_persistence import record_legacy_match, promote_offer
from scenthunter_next_engine.canonical_matcher import CanonicalMatcher
from scenthunter_next_engine.catalog_repository import CatalogRepository
from scenthunter_next_engine.offer_normalizer import normalize_offer


_SIZE_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl|dl|l)\b", re.I)


def _explicit_title_size(title: str) -> int | None:
    match = _SIZE_RE.search(title or "")
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    value *= {"ml": 1, "cl": 10, "dl": 100, "l": 1000}[match.group(2).lower()]
    if value <= 0 or value > 10000 or not value.is_integer():
        return None
    return int(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="persist verified matches and offers")
    parser.add_argument("--catalog", default="/app/backend/product_catalog.json")
    args = parser.parse_args()

    catalog = CatalogRepository.from_file(args.catalog)
    matcher = CanonicalMatcher(catalog)
    engine = make_engine()
    try:
        with Session(engine) as session:
            store = session.scalar(select(Store).where(Store.slug == "bplatz"))
            if store is None or store.status != "active":
                raise SystemExit("BPLATZ_STORE_NOT_ACTIVE")
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
                if not gtin:
                    skipped["missing_gtin"] += 1
                    continue
                if gtin in seen_gtins:
                    duplicate_rows += 1
                    continue
                seen_gtins.add(gtin)

                title = str(payload.get("raw_name") or payload.get("name") or "")
                match_payload = dict(payload)
                explicit_size = match_payload.get("size_ml")
                if explicit_size in (None, ""):
                    explicit_size = _explicit_title_size(title)
                    if explicit_size is not None:
                        match_payload["size_ml"] = explicit_size

                try:
                    offer = normalize_offer(
                        match_payload, retailer="Bplatz", currency_default="EUR",
                    )
                    matched = matcher.match(offer)
                except (TypeError, ValueError):
                    skipped["normalization_failed"] += 1
                    continue

                if matched.reason != "verified_gtin_exact_variant":
                    skipped[matched.reason or matched.status.value] += 1
                    continue
                if offer.size_ml is None:
                    skipped["missing_explicit_size"] += 1
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
                if not _offer_url_valid(offer.product_url, store.domain):
                    skipped["invalid_store_url"] += 1
                    continue

                latest_by_gtin[gtin] = {
                    "row": row,
                    "payload": match_payload,
                    "offer": offer,
                    "match": matched,
                }

            candidates = list(latest_by_gtin.values())
            summary = {
                "mode": "apply" if args.apply else "dry_run",
                "pending_rows": len(rows),
                "verified_gtin_candidates": len(candidates),
                "unique_gtin_candidates": len(latest_by_gtin),
                "duplicate_rows_suppressed": duplicate_rows,
                "in_stock_candidates": sum(x["offer"].availability == "in_stock" for x in candidates),
                "out_of_stock_candidates": sum(x["offer"].availability == "out_of_stock" for x in candidates),
                "skipped_reasons": dict(sorted(skipped.items())),
                "candidates": [
                    {
                        "raw_id": str(x["row"].id),
                        "gtin": gtin,
                        "product_id": x["match"].canonical_product_id,
                        "variant_id": x["match"].canonical_variant_id,
                        "brand": x["offer"].brand_raw,
                        "name": x["offer"].raw_name,
                        "size_ml": x["offer"].size_ml,
                        "price": str(x["offer"].price),
                        "currency": x["offer"].currency,
                        "availability": x["offer"].availability,
                        "url_host": urlparse(x["offer"].product_url or "").hostname,
                    }
                    for gtin, x in sorted(latest_by_gtin.items())
                ],
                "database_written": False,
            }

            if args.apply:
                promoted = 0
                with session.begin_nested():
                    for gtin, item in sorted(latest_by_gtin.items()):
                        row = item["row"]
                        offer = item["offer"]
                        matched = item["match"]
                        payload = dict(item["payload"])
                        payload["size_ml"] = offer.size_ml
                        payload["canonical_gtin_backfill"] = {
                            "gtin": gtin,
                            "product_id": matched.canonical_product_id,
                            "variant_id": matched.canonical_variant_id,
                            "method": "reviewed_verified_gtin_registry",
                        }
                        row.raw_payload = payload
                        resolved = record_legacy_match(
                            session,
                            ingestion_raw_id=row.id,
                            legacy_product_id=matched.canonical_product_id,
                            legacy_variant_id=matched.canonical_variant_id,
                            method="bplatz_verified_gtin_registry",
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
                            source="bplatz_verified_gtin_registry",
                            confidence=matched.confidence,
                        )
                        promoted += 1
                session.commit()
                summary["promoted_unique_gtins"] = promoted
                summary["database_written"] = True

            print("BPLATZ_VERIFIED_GTIN_BACKFILL=" + json.dumps(
                summary, ensure_ascii=False, sort_keys=True,
            ))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
