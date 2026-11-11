"""Verify Notino Phase 2 data in the isolated persistent SQLite database."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from urllib.parse import urlparse


def _metrics(database: Path) -> dict:
    if not database.is_file():
        raise SystemExit(f"STOP: Phase 2 database does not exist: {database}")
    uri = f"file:{database.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        offers = connection.execute(
            "SELECT o.id, o.price, o.currency, o.availability, o.url, "
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

    invalid = 0
    for (
        _offer_id, price, currency, availability, url, variant_id, status,
        source, captured_at, store_status, fragrance_id, has_legacy_mapping,
    ) in offers:
        parsed = urlparse(url or "")
        if (
            float(price or 0) <= 0
            or currency != "EUR"
            or availability not in {"in_stock", "out_of_stock"}
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or not variant_id
            or not fragrance_id
            or not has_legacy_mapping
            or not captured_at
            or store_status != "active"
            or status != "active"
            or source != "cj_notino_fr_feed"
        ):
            invalid += 1

    return {
        "db_exists": True,
        "offers": len(offers),
        "distinct_matched_variants": len({row[5] for row in offers if row[5]}),
        "price_history": history,
        "raw_rows": raw_rows,
        "duplicate_external_ids": duplicates,
        "invalid_offers": invalid,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("/data/notino-phase2/catalog.sqlite3"))
    parser.add_argument("--write-baseline", type=Path)
    parser.add_argument("--compare-baseline", type=Path)
    args = parser.parse_args()

    database = args.database.expanduser().resolve()
    if Path("/data") not in database.parents:
        raise SystemExit("STOP: Phase 2 verification is restricted to /data")
    result = _metrics(database)
    failures = []
    if result["offers"] <= 0:
        failures.append("no_published_notino_offers")
    if result["distinct_matched_variants"] <= 0:
        failures.append("no_canonical_variant_matches")
    if result["price_history"] < result["offers"]:
        failures.append("missing_price_history")
    if result["raw_rows"] < result["offers"]:
        failures.append("raw_offer_rows_missing")
    if result["duplicate_external_ids"]:
        failures.append("duplicate_offer_external_ids")
    if result["invalid_offers"]:
        failures.append("invalid_published_offers")

    if args.write_baseline:
        args.write_baseline.write_text(json.dumps(result), encoding="utf-8")
    if args.compare_baseline:
        before = json.loads(args.compare_baseline.read_text(encoding="utf-8"))
        if result["offers"] != before["offers"]:
            failures.append("offer_count_changed_on_reimport")
        if result["price_history"] <= before["price_history"]:
            failures.append("reimport_did_not_record_new_observations")

    result.update({
        "status": "passed" if not failures else "failed",
        "verification_failures": failures,
        "database_path": str(database),
    })
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
