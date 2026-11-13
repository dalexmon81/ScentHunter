"""Import the authorized Notino CJ snapshot into an explicitly isolated persistent Phase 2 SQLite DB.

This command refuses paths outside /data and requires --apply. It never uses the
legacy catalog DB path or production credentials. Exact GTIN matches only.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.db import make_engine
from app.models import (
    Base, IngestionRaw, LegacyProductIdMap, LegacyVariantIdMap, NotinoFeedListing, Offer,
    PriceHistory, ProductVariant, Store,
)
from app.services.notino_phase2_adapter import persist_notino_record
from app.services.notino_feed_listings import refresh_notino_listings
from scripts.build_notino_match_candidates import iter_perfume_rows
from scripts.seed_catalog import stable_id
from gtin import is_valid_gtin


def money(value: str):
    import re
    match = re.search(r"([0-9][0-9.,]*)\s*([A-Z]{3})", (value or "").strip(), re.I)
    if not match:
        return None, None
    number, currency = match.groups()
    if "," in number and "." in number:
        number = number.replace(".", "").replace(",", ".")
    elif "," in number:
        number = number.replace(",", ".")
    try:
        return Decimal(number), currency.upper()
    except InvalidOperation:
        return None, currency.upper()


def _duplicate_valid_feed_gtins(rows: list[dict]) -> set[str]:
    """Return valid GTINs repeated across distinct feed rows; never auto-match them."""
    counts = Counter(
        str(row.get("gtin") or "").strip()
        for row in rows
        if is_valid_gtin(str(row.get("gtin") or "").strip())
    )
    return {gtin for gtin, count in counts.items() if count > 1}


def _audit_feed_rows(rows: list[dict]) -> dict:
    """Validate a feed snapshot in isolated in-memory SQLite; never touch /data."""
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session, session.begin():
            snapshot = refresh_notino_listings(
                session, rows, datetime.now(timezone.utc),
            )
            accepted_brands = session.scalars(
                select(NotinoFeedListing.brand).distinct()
            ).all()
        return {
            "accepted_listings": int(snapshot["listings"]),
            "accepted_brand_count": len(accepted_brands),
            "rejected": dict(snapshot["rejected"]),
        }
    finally:
        engine.dispose()


def _stage_unmatched_rows_bulk(
    session: Session, store_id: UUID, rows: list[dict],
) -> None:
    """Persist unresolved feed rows in one executemany instead of per-row flushes."""
    if not rows:
        return
    session.bulk_insert_mappings(
        IngestionRaw,
        [
            {
                "id": uuid4(),
                "store_id": store_id,
                "raw_payload": row["raw_payload"],
                "external_product_id": row["external_product_id"],
                "status": "pending",
                "match_method": row["match_method"],
                "rejection_reason": row["reason"],
            }
            for row in rows
        ],
    )


def _count_retailer_only_listings(session: Session, store_id: UUID) -> int:
    has_canonical_offer = select(Offer.id).where(
        Offer.store_id == store_id,
        Offer.external_product_id == NotinoFeedListing.external_id,
    ).exists()
    return session.scalar(
        select(func.count()).select_from(NotinoFeedListing).where(
            ~has_canonical_offer
        )
    ) or 0


def _seed_canonical_catalog(engine, catalog_path: Path) -> bool:
    seed_script = BACKEND / "scripts" / "seed_catalog.py"
    catalog_path = catalog_path.resolve()
    command = [sys.executable, str(seed_script), "--catalog", str(catalog_path)]
    validation = subprocess.run(
        command, check=True, cwd=ROOT, env=os.environ.copy(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    validation_report = json.loads(validation.stdout)
    if validation_report.get("status") != "validated":
        raise RuntimeError("Canonical catalog validation did not pass")

    with catalog_path.open(encoding="utf-8") as handle:
        catalog = json.load(handle)
    products = catalog["products"]
    variants = catalog["variants"]
    product_ids = {str(row["product_id"]).strip() for row in products}
    product_id_by_variant = {
        str(row["variant_id"]).strip(): str(row["product_id"]).strip()
        for row in variants
    }
    variant_ids = set(product_id_by_variant)

    with Session(engine) as session, session.begin():
        existing_products = dict(session.execute(
            select(
                LegacyProductIdMap.legacy_product_id,
                LegacyProductIdMap.fragrance_id,
            )
        ).all())
        existing_variants = dict(session.execute(
            select(LegacyVariantIdMap.legacy_variant_id, ProductVariant)
            .join(ProductVariant, ProductVariant.id == LegacyVariantIdMap.product_variant_id)
        ).all())
        canonical_identities_ready = all(
            existing_products.get(product_id) == stable_id("fragrance", product_id)
            for product_id in product_ids
        ) and all(
            source_id in existing_variants
            and existing_variants[source_id].id == stable_id("variant", source_id)
            and existing_variants[source_id].fragrance_id
            == stable_id("fragrance", product_id_by_variant[source_id])
            for source_id in variant_ids
        )
        if canonical_identities_ready:
            gtins_updated = 0
            for row in variants:
                source_id = str(row["variant_id"]).strip()
                variant = existing_variants[source_id]
                if variant.gtin:
                    continue
                raw_gtins = row.get("gtins")
                if not isinstance(raw_gtins, list):
                    raw_gtins = [row.get("gtin")]
                valid_gtins = sorted({
                    str(value).strip() for value in raw_gtins
                    if value not in (None, "") and is_valid_gtin(str(value).strip())
                })
                if valid_gtins:
                    variant.gtin = valid_gtins[0]
                    gtins_updated += 1
            print(
                f"Canonical catalog already seeded; filled {gtins_updated} "
                "previously missing variant GTIN(s).",
                flush=True,
            )
            return False

    applied = subprocess.run(
        [*command, "--apply"], check=True, cwd=ROOT, env=os.environ.copy(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    print(applied.stdout, end="", flush=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feed", type=Path)
    parser.add_argument("--database", type=Path, default=Path("/data/notino-phase2/catalog.sqlite3"))
    parser.add_argument("--catalog", type=Path, default=BACKEND / "product_catalog.json")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()

    if args.apply == args.audit_only:
        raise SystemExit("STOP: choose exactly one of --apply or --audit-only")
    if not args.feed.is_file() or args.feed.stat().st_size == 0:
        raise SystemExit("STOP: feed missing or empty")
    if args.apply:
        db_path = args.database.resolve()
        if Path("/data") not in db_path.parents:
            raise SystemExit("STOP: persistent Phase 2 database must be below /data")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        os.environ["SCENTHUNTER_CATALOG_DATABASE_URL"] = f"sqlite:///{db_path}"

    import_started = time.monotonic()
    rows = []
    parsed_entries = 0
    print(
        f"IMPORT_PHASE feed_parse_started bytes={args.feed.stat().st_size}",
        flush=True,
    )
    for row in iter_perfume_rows(args.feed):
        rows.append(row)
        parsed_entries += 1
        if parsed_entries % 1000 == 0:
            print(
                f"IMPORT_PROGRESS feed_rows_parsed={parsed_entries} "
                f"elapsed_seconds={time.monotonic() - import_started:.1f}",
                flush=True,
            )
    ids = [str(row.get("id") or "").strip() for row in rows]
    if not rows or any(not x for x in ids) or len(ids) != len(set(ids)):
        raise SystemExit("STOP: feed has empty or duplicate retailer product IDs")
    duplicate_feed_gtins = _duplicate_valid_feed_gtins(rows)
    duplicate_feed_gtin_rows = sum(
        1 for row in rows
        if str(row.get("gtin") or "").strip() in duplicate_feed_gtins
    )
    print(
        f"IMPORT_PHASE feed_parsed rows={len(rows)} "
        f"duplicate_valid_gtin_values={len(duplicate_feed_gtins)} "
        f"duplicate_gtin_rows={duplicate_feed_gtin_rows} "
        f"elapsed_seconds={time.monotonic() - import_started:.1f}",
        flush=True,
    )

    if args.audit_only:
        audit = _audit_feed_rows(rows)
        rejected_count = sum(audit["rejected"].values())
        result = {
            "status": "passed" if audit["accepted_listings"] + rejected_count == len(rows) else "failed",
            "mode": "read_only_in_memory_audit",
            "feed_bytes": args.feed.stat().st_size,
            "feed_rows": len(rows),
            "feed_brand_count": len({str(row.get("brand") or "").strip() for row in rows if str(row.get("brand") or "").strip()}),
            "accepted_listings": audit["accepted_listings"],
            "accepted_brand_count": audit["accepted_brand_count"],
            "rejected_rows": rejected_count,
            "rejected": audit["rejected"],
            "duplicate_feed_gtin_values": len(duplicate_feed_gtins),
            "duplicate_feed_gtin_rows": duplicate_feed_gtin_rows,
            "persistent_database_touched": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "passed" else 2

    # Idempotently seed canonical identities into this isolated database.
    engine = make_engine()
    try:
        Base.metadata.create_all(engine)
        seed_started = time.monotonic()
        print("IMPORT_PHASE canonical_seed_started", flush=True)
        _seed_canonical_catalog(engine, args.catalog)
        print(
            f"IMPORT_PHASE canonical_seed_finished "
            f"elapsed_seconds={time.monotonic() - seed_started:.1f}",
            flush=True,
        )
        counts, reasons = Counter(), Counter()
        snapshot_time = datetime.now(timezone.utc)
        observed_at = snapshot_time.isoformat()
        with Session(engine) as session, session.begin():
            store = session.scalar(select(Store).where(Store.slug == "notino-fr"))
            if store is None:
                store = Store(id=uuid4(), name="NOTINO.fr", slug="notino-fr",
                              domain="notino.fr", country="FR", currency="EUR", status="active")
                session.add(store)
                session.flush()
            store_id = store.id
            # Read the existing retailer IDs once. Per-row SELECTs made repeat
            # imports perform ~19,000 SQLite round trips for a 9.5k-row feed.
            existing_offer_ids = set(session.scalars(
                select(Offer.external_product_id).where(
                    Offer.store_id == store_id,
                    Offer.external_product_id.is_not(None),
                )
            ).all())
            existing_raw_ids = set(session.scalars(
                select(IngestionRaw.external_product_id).where(
                    IngestionRaw.store_id == store_id,
                    IngestionRaw.external_product_id.is_not(None),
                )
            ).all())
            already_published_duplicate_ids = {
                str(row.get("id") or "").strip()
                for row in rows
                if str(row.get("gtin") or "").strip() in duplicate_feed_gtins
                and str(row.get("id") or "").strip() in existing_offer_ids
            }
            if already_published_duplicate_ids:
                raise RuntimeError(
                    "duplicate_feed_gtin_conflicts_with_existing_canonical_offers:"
                    + ",".join(sorted(already_published_duplicate_ids)[:10])
                )

            variants_by_gtin: dict[str, list] = {}
            for gtin, variant_id in session.execute(
                select(ProductVariant.gtin, ProductVariant.id).where(
                    ProductVariant.gtin.is_not(None)
                )
            ):
                variants_by_gtin.setdefault(gtin, []).append(variant_id)

            unmatched_rows = []
            row_started = time.monotonic()
            for index, row in enumerate(rows, start=1):
                if index % 1000 == 0:
                    print(
                        f"IMPORT_PROGRESS rows_scanned={index}/{len(rows)} "
                        f"unmatched_prepared={len(unmatched_rows)} "
                        f"elapsed_seconds={time.monotonic() - row_started:.1f}",
                        flush=True,
                    )
                external_id = str(row.get("id") or "").strip()
                gtin = str(row.get("gtin") or "").strip()
                matching_variants = (
                    variants_by_gtin.get(gtin, [])
                    if is_valid_gtin(gtin) and gtin not in duplicate_feed_gtins
                    else []
                )
                # Do not re-stage thousands of unchanged unmatched feed rows.
                # Existing published offers are re-observed to refresh price/stock.
                # If canonical GTIN coverage has since changed, retry the row.
                if (
                    external_id in existing_raw_ids
                    and external_id not in existing_offer_ids
                    and len(matching_variants) != 1
                ):
                    counts["unchanged_unmatched_skipped"] += 1
                    continue

                price, price_currency = money(row.get("price", ""))
                sale_price, sale_currency = money(row.get("sale_price", ""))
                if sale_price is not None and sale_price <= 0:
                    sale_price = None
                record = {
                    "external_id": external_id,
                    "gtin": str(row.get("gtin") or "").strip(),
                    "price": str(price) if price is not None else None,
                    "sale_price": str(sale_price) if sale_price is not None else None,
                    "currency": sale_currency or price_currency or "EUR",
                    "availability": str(row.get("availability") or "").strip().casefold(),
                    "affiliate_url": str(row.get("link") or "").strip(),
                    "captured_at": observed_at,
                    "source_last_updated": str(row.get("last_updated") or "").strip() or None,
                    "title": str(row.get("title") or "").strip(),
                }
                if len(matching_variants) != 1:
                    if gtin in duplicate_feed_gtins:
                        reason = "duplicate_gtin_in_feed_snapshot"
                        method = "notino_duplicate_gtin"
                    elif not is_valid_gtin(gtin):
                        reason = "invalid_gtin_check_digit"
                        method = "notino_gtin_check_digit"
                    elif not matching_variants:
                        reason = "gtin_not_in_canonical_catalog"
                        method = "notino_exact_gtin"
                    else:
                        reason = "gtin_matches_multiple_canonical_variants"
                        method = "notino_exact_gtin"
                    unmatched_rows.append({
                        "external_product_id": external_id,
                        "raw_payload": record,
                        "match_method": method,
                        "reason": reason,
                    })
                    counts["pending"] += 1
                    reasons[reason] += 1
                    continue

                result = persist_notino_record(session, store_id=store_id, raw_record=record)
                counts[result.status] += 1
                if result.reason:
                    reasons[result.reason] += 1

            print(
                f"IMPORT_PHASE row_processing_finished "
                f"rows={len(rows)} unmatched_batch={len(unmatched_rows)} "
                f"elapsed_seconds={time.monotonic() - row_started:.1f}",
                flush=True,
            )
            _stage_unmatched_rows_bulk(session, store_id, unmatched_rows)
            feed_snapshot = refresh_notino_listings(session, rows, snapshot_time)
            offers = session.scalar(select(func.count()).select_from(Offer).where(Offer.store_id == store_id)) or 0
            history = session.scalar(select(func.count()).select_from(PriceHistory).join(Offer).where(Offer.store_id == store_id)) or 0
            raw_count = session.scalar(select(func.count()).select_from(IngestionRaw).where(IngestionRaw.store_id == store_id)) or 0
            retailer_only = _count_retailer_only_listings(session, store_id)
            duplicates = session.execute(
                select(Offer.external_product_id, func.count())
                .where(Offer.store_id == store_id, Offer.external_product_id.is_not(None))
                .group_by(Offer.external_product_id).having(func.count() > 1)
            ).all()
            result = {
                "status": "passed" if offers > 0 and history >= offers and not duplicates else "failed",
                "feed_rows": len(rows), "adapter_results": dict(counts),
                "retailer_only_snapshot": feed_snapshot,
                "hold_reasons": dict(reasons), "persistent_offers": offers,
                "canonical_offer_count": offers,
                "retailer_only_listing_count": retailer_only,
                "duplicate_feed_gtin_values": len(duplicate_feed_gtins),
                "duplicate_feed_gtin_rows": duplicate_feed_gtin_rows,
                "unmatched_rows_staged_in_batch": len(unmatched_rows),
                "price_history_rows": history, "raw_rows_persisted": raw_count,
                "duplicate_offer_external_ids": len(duplicates),
                "database_path": str(db_path), "database_scope": "dedicated isolated staging volume",
                "production_database_touched": False,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "passed" else 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
