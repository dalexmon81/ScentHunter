"""Read-only Phase 2 catalog verifier with optional Bplatz before/after checks."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import inspect, text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.db import database_url, make_engine

EXPECTED = {
    "brands", "fragrances", "product_variants", "stores", "offers",
    "price_history", "match_audit", "ingestion_runs", "ingestion_raw",
}


def collect_report(connection):
    journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower()
    foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
    integrity = connection.exec_driver_sql("PRAGMA integrity_check").scalar_one()
    foreign_key_violations = len(
        connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    )
    tables = set(inspect(connection).get_table_names())
    missing = sorted(EXPECTED - tables)
    if missing:
        raise RuntimeError(f"Missing catalog tables: {missing}")

    invalid_active = connection.execute(text(
        "SELECT COUNT(*) FROM offers WHERE status = 'active' AND "
        "(price IS NULL OR url IS NULL OR length(trim(url)) = 0 OR availability IS NULL)"
    )).scalar_one()
    counts = {
        name: connection.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar_one()
        for name in sorted(EXPECTED)
    }

    store = connection.execute(text(
        "SELECT id, name, slug FROM stores WHERE slug = 'bplatz'"
    )).mappings().first()
    if store is None:
        raise RuntimeError("Bplatz store row is missing")
    store_id = store["id"]

    bplatz = {
        "offers": connection.execute(text(
            "SELECT COUNT(*) FROM offers WHERE store_id = :store_id"
        ), {"store_id": store_id}).scalar_one(),
        "raw_rows": connection.execute(text(
            "SELECT COUNT(*) FROM ingestion_raw WHERE store_id = :store_id"
        ), {"store_id": store_id}).scalar_one(),
        "active_offers": connection.execute(text(
            "SELECT COUNT(*) FROM offers WHERE store_id = :store_id AND status = 'active'"
        ), {"store_id": store_id}).scalar_one(),
        "price_history": connection.execute(text("""
            SELECT COUNT(*) FROM price_history ph
            JOIN offers o ON o.id = ph.offer_id
            WHERE o.store_id = :store_id
        """), {"store_id": store_id}).scalar_one(),
        "match_audit": connection.execute(text("""
            SELECT COUNT(*) FROM match_audit ma
            JOIN offers o ON o.id = ma.offer_id
            WHERE o.store_id = :store_id
        """), {"store_id": store_id}).scalar_one(),
        "duplicate_external_product_ids": connection.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT external_product_id
                FROM offers
                WHERE store_id = :store_id AND external_product_id IS NOT NULL
                GROUP BY external_product_id
                HAVING COUNT(*) > 1
            )
        """), {"store_id": store_id}).scalar_one(),
        "current_offer_linked_to_promoted_raw": connection.execute(text("""
            SELECT COUNT(*) FROM offers o
            JOIN ingestion_raw ir ON ir.id = o.ingestion_raw_id
            WHERE o.store_id = :store_id AND ir.status = 'promoted'
        """), {"store_id": store_id}).scalar_one(),
    }

    return {
        "database_url": database_url(),
        "journal_mode": journal_mode,
        "foreign_keys": foreign_keys,
        "foreign_key_violations": foreign_key_violations,
        "integrity_check": integrity,
        "tables": sorted(tables),
        "row_counts": counts,
        "invalid_active_offers": invalid_active,
        "bplatz": bplatz,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot", action="store_true",
        help="print a read-only baseline snapshot for the next normal Bplatz hydration",
    )
    parser.add_argument(
        "--baseline", type=Path,
        help="compare current read-only state with a JSON snapshot",
    )
    parser.add_argument(
        "--snapshot-file", type=Path,
        help="write a clean JSON baseline file (without console status lines)",
    )
    parser.add_argument("--worker-ingestion-raw-id", help="raw UUID from the normal-worker correlation log")
    parser.add_argument("--worker-offer-id", help="offer UUID from the normal-worker correlation log")
    parser.add_argument("--worker-sku", help="SKU from the normal-worker correlation log")
    args = parser.parse_args()

    engine = make_engine()
    try:
        with engine.connect() as connection:
            report = collect_report(connection)
        print(json.dumps(report, indent=2, sort_keys=True, default=str))

        checks = {
            "JOURNAL_MODE": report["journal_mode"] == "wal",
            "FOREIGN_KEYS": report["foreign_keys"] == 1 and report["foreign_key_violations"] == 0,
            "INTEGRITY_CHECK": report["integrity_check"] == "ok",
            "INVALID_ACTIVE_OFFERS": report["invalid_active_offers"] == 0,
            "BPLATZ_ACTIVE_OFFER": report["bplatz"]["active_offers"] > 0,
            "BPLATZ_CURRENT_PROMOTION": report["bplatz"]["current_offer_linked_to_promoted_raw"] > 0,
            "DUPLICATES": report["bplatz"]["duplicate_external_product_ids"] == 0,
        }

        if args.snapshot:
            failed = [name for name, passed in checks.items() if not passed]
            if args.snapshot_file:
                args.snapshot_file.write_text(
                    json.dumps(report, indent=2, sort_keys=True, default=str) + "\\n",
                    encoding="utf-8",
                )
            if failed:
                print("BASELINE=FAIL checks=" + ",".join(failed))
                return 1
            print("BASELINE=PASS")
            return 0

        if args.baseline:
            baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
            before = baseline["bplatz"]
            after = report["bplatz"]
            checks["OFFER_UPSERT"] = after["offers"] == before["offers"]
            checks["PRICE_HISTORY"] = after["price_history"] > before["price_history"]
            checks["MATCH_AUDIT"] = after["match_audit"] > before["match_audit"]
            checks["RAW_INGESTION"] = after["raw_rows"] > before["raw_rows"]

            print(
                "OFFER_UPSERT="
                + ("PASS" if checks["OFFER_UPSERT"] else "FAIL")
                + f" baseline={before['offers']} current={after['offers']}"
            )
            print(
                "PRICE_HISTORY="
                + ("PASS" if checks["PRICE_HISTORY"] else "FAIL")
                + f" baseline={before['price_history']} current={after['price_history']}"
            )
            print(
                "MATCH_AUDIT="
                + ("PASS" if checks["MATCH_AUDIT"] else "FAIL")
                + f" baseline={before['match_audit']} current={after['match_audit']}"
            )
            print(
                "RAW_INGESTION="
                + ("PASS" if checks["RAW_INGESTION"] else "FAIL")
                + f" baseline={before['raw_rows']} current={after['raw_rows']}"
            )

        if args.worker_ingestion_raw_id or args.worker_offer_id or args.worker_sku:
            if not (args.worker_ingestion_raw_id and args.worker_offer_id and args.worker_sku):
                raise ValueError("worker proof requires raw ID, offer ID, and SKU together")
            with engine.connect() as connection:
                store_id = connection.execute(text(
                    "SELECT id FROM stores WHERE slug = 'bplatz'"
                )).scalar_one()
                worker_row = connection.execute(text("""
                    SELECT ir.status, ir.raw_payload
                    FROM ingestion_raw ir
                    JOIN offers o ON o.ingestion_raw_id = ir.id
                    WHERE ir.id = :raw_id AND o.id = :offer_id
                      AND ir.store_id = :store_id AND o.store_id = :store_id
                """), {
                    "raw_id": args.worker_ingestion_raw_id,
                    "offer_id": args.worker_offer_id,
                    "store_id": store_id,
                }).mappings().first()
            payload = worker_row["raw_payload"] if worker_row else None
            if isinstance(payload, str):
                payload = json.loads(payload)
            worker_proof = bool(
                worker_row
                and worker_row["status"] == "promoted"
                and isinstance(payload, dict)
                and str(payload.get("sku") or "") == args.worker_sku
            )
            checks["WORKER_LOG"] = worker_proof
            print("WORKER_LOG=" + ("PASS" if worker_proof else "FAIL")
                  + f" sku={args.worker_sku} raw_id={args.worker_ingestion_raw_id}")

        for name, passed in checks.items():
            if name in {"OFFER_UPSERT", "PRICE_HISTORY", "MATCH_AUDIT"} and not args.baseline:
                continue
            value = report["integrity_check"] if name == "INTEGRITY_CHECK" else (
                report["bplatz"]["duplicate_external_product_ids"]
                if name == "DUPLICATES" else ("PASS" if passed else "FAIL")
            )
            if name == "INTEGRITY_CHECK":
                print(f"INTEGRITY_CHECK={value}")
            elif name == "DUPLICATES":
                print(f"DUPLICATES={'PASS' if passed else 'FAIL'} count={value}")
            else:
                print(f"{name}={'PASS' if passed else 'FAIL'}")

        success = all(checks.values())
        print("VERIFIER=" + ("PASS" if success else "FAIL"))
        return 0 if success else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
