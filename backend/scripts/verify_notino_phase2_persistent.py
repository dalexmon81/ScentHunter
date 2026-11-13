"""Verify Notino Phase 2 data in the isolated persistent SQLite database."""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from app.services.notino_affiliate import is_valid_notino_affiliate_url


def _metrics(database: Path) -> dict:
    if not database.is_file():
        raise SystemExit(f"STOP: Phase 2 database does not exist: {database}")
    uri = f"file:{database.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        offers = connection.execute(
            "SELECT o.id, o.external_product_id, o.price, o.currency, o.availability, o.url, "
            "o.product_variant_id, o.status, o.source, o.captured_at, s.status, "
            "v.fragrance_id, "
            "EXISTS(SELECT 1 FROM legacy_product_id_map m "
            "WHERE m.fragrance_id = v.fragrance_id) FROM offers o "
            "JOIN stores s ON s.id = o.store_id "
            "LEFT JOIN product_variants v ON v.id = o.product_variant_id "
            "WHERE s.slug = ?",
            ("notino-fr",),
        ).fetchall()
        history = connection.execute(
            "SELECT COUNT(*) FROM price_history h "
            "JOIN offers o ON o.id = h.offer_id "
            "JOIN stores s ON s.id = o.store_id WHERE s.slug = ?",
            ("notino-fr",),
        ).fetchone()[0]
        raw_rows = connection.execute(
            "SELECT COUNT(*) FROM ingestion_raw r "
            "JOIN stores s ON s.id = r.store_id WHERE s.slug = ?",
            ("notino-fr",),
        ).fetchone()[0]
        duplicates = connection.execute(
            "SELECT COUNT(*) FROM (SELECT o.external_product_id FROM offers o "
            "JOIN stores s ON s.id = o.store_id WHERE s.slug = ? "
            "AND o.external_product_id IS NOT NULL "
            "GROUP BY o.external_product_id HAVING COUNT(*) > 1)",
            ("notino-fr",),
        ).fetchone()[0]
        retailer_listings = connection.execute(
            "SELECT external_id, brand, title, price, currency, availability, "
            "affiliate_url, source_last_updated FROM notino_feed_listings"
        ).fetchall()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()

    invalid = 0
    canonical_external_ids = set()
    for (
        _offer_id, external_id, price, currency, availability, url, variant_id, status,
        source, captured_at, store_status, fragrance_id, has_legacy_mapping,
    ) in offers:
        canonical_external_ids.add(external_id)
        if (
            float(price or 0) <= 0
            or currency != "EUR"
            or availability not in {"in_stock", "out_of_stock"}
            or not is_valid_notino_affiliate_url(url or "")
            or not variant_id
            or not fragrance_id
            or not has_legacy_mapping
            or not captured_at
            or store_status != "active"
            or status != "active"
            or source != "cj_notino_fr_feed"
        ):
            invalid += 1

    invalid_listings = 0
    retailer_external_ids = set()
    for external_id, brand, title, price, currency, availability, url, updated in retailer_listings:
        retailer_external_ids.add(external_id)
        try:
            timestamp = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
            valid_timestamp = timestamp.tzinfo is not None and timestamp.utcoffset() is not None
        except ValueError:
            valid_timestamp = False
        if (
            not external_id or not brand or not title
            or float(price or 0) <= 0 or currency != "EUR"
            or availability not in {"in stock", "out of stock"}
            or not is_valid_notino_affiliate_url(url or "")
            or not valid_timestamp
        ):
            invalid_listings += 1

    return {
        "db_exists": True,
        "offers": len(offers),
        "canonical_offers": len(offers),
        "distinct_matched_variants": len({row[6] for row in offers if row[6]}),
        "retailer_listings": len(retailer_listings),
        "retailer_only_listings": len(retailer_external_ids - canonical_external_ids),
        "price_history": history,
        "raw_rows": raw_rows,
        "duplicate_external_ids": duplicates,
        "invalid_offers": invalid,
        "invalid_retailer_listings": invalid_listings,
        "sqlite_integrity": integrity,
        "foreign_key_errors": len(foreign_key_errors),
    }


def _preflight(database: Path) -> dict:
    marker = database.parent / "notino-cj-feed.imported.sha256"
    imported_sha = marker.read_text(encoding="ascii").strip() if marker.is_file() else None
    result = {
        "database_exists": database.is_file(),
        "sqlite_integrity": "not_created",
        "foreign_key_errors": 0,
        "canonical_offers": 0,
        "retailer_listings": 0,
        "duplicate_external_ids": 0,
        "imported_snapshot_sha": imported_sha,
    }
    if not database.is_file():
        result["status"] = "passed"
        return result

    uri = f"file:{database.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        result["sqlite_integrity"] = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]
        result["foreign_key_errors"] = len(
            connection.execute("PRAGMA foreign_key_check").fetchall()
        )
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if {"offers", "stores"} <= tables:
            result["canonical_offers"] = connection.execute(
                "SELECT COUNT(*) FROM offers o JOIN stores s ON s.id = o.store_id "
                "WHERE s.slug = ?",
                ("notino-fr",),
            ).fetchone()[0]
            result["duplicate_external_ids"] = connection.execute(
                "SELECT COUNT(*) FROM (SELECT o.external_product_id FROM offers o "
                "JOIN stores s ON s.id = o.store_id WHERE s.slug = ? "
                "AND o.external_product_id IS NOT NULL GROUP BY o.external_product_id "
                "HAVING COUNT(*) > 1)",
                ("notino-fr",),
            ).fetchone()[0]
        if "notino_feed_listings" in tables:
            result["retailer_listings"] = connection.execute(
                "SELECT COUNT(*) FROM notino_feed_listings"
            ).fetchone()[0]
    result["status"] = (
        "passed" if result["sqlite_integrity"] == "ok"
        and not result["foreign_key_errors"]
        and not result["duplicate_external_ids"]
        else "failed"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("/data/notino-phase2/catalog.sqlite3"))
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--write-baseline", type=Path)
    parser.add_argument("--compare-baseline", type=Path)
    args = parser.parse_args()

    database = args.database.expanduser().resolve()
    if Path("/data") not in database.parents:
        raise SystemExit("STOP: Phase 2 verification is restricted to /data")
    if args.preflight:
        result = _preflight(database)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] == "passed" else 2
    result = _metrics(database)
    failures = []
    if result["offers"] <= 0:
        failures.append("no_published_notino_offers")
    if result["retailer_listings"] <= 0:
        failures.append("no_persisted_retailer_listings")
    if result["price_history"] < result["offers"]:
        failures.append("missing_price_history")
    if result["raw_rows"] < result["offers"]:
        failures.append("raw_offer_rows_missing")
    if result["duplicate_external_ids"]:
        failures.append("duplicate_offer_external_ids")
    if result["invalid_offers"]:
        failures.append("invalid_published_offers")
    if result["invalid_retailer_listings"]:
        failures.append("invalid_persisted_retailer_listings")
    if result["sqlite_integrity"] != "ok":
        failures.append("sqlite_integrity_check_failed")
    if result["foreign_key_errors"]:
        failures.append("foreign_key_check_failed")

    if args.write_baseline:
        args.write_baseline.write_text(json.dumps(result), encoding="utf-8")
    if args.compare_baseline:
        before = json.loads(args.compare_baseline.read_text(encoding="utf-8"))
        if result["offers"] != before["offers"]:
            failures.append("offer_count_changed_on_reimport")
        if result["price_history"] != before["price_history"]:
            failures.append("price_history_changed_on_identical_reimport")
        if result["retailer_listings"] != before["retailer_listings"]:
            failures.append("retailer_listing_count_changed_on_reimport")

    result.update({
        "status": "passed" if not failures else "failed",
        "verification_failures": failures,
        "database_path": str(database),
    })
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
