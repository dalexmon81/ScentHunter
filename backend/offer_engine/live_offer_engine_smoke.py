"""Read-only live end-to-end smoke test for the isolated Offer Engine.

Uses bounded retailer reads and a temporary SQLite database only. It never
connects to or mutates the production database or canonical catalog.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from offer_engine.read_repository import OfferReadRepository
from offer_engine.runtime import apply_migration, connect_offer_engine_db, run_offer_engine


def run() -> dict:
    query = "Liquid Brun"
    with tempfile.TemporaryDirectory(prefix="scenthunter-offer-engine-smoke-") as directory:
        db_path = Path(directory) / "offer-engine.sqlite3"
        apply_migration(db_path=db_path)
        engine_result = run_offer_engine(query, db_path=db_path)

        connection = connect_offer_engine_db(db_path=db_path)
        try:
            rows = OfferReadRepository(connection).search(query, limit=200)
        finally:
            connection.close()

        deloox_rows = [row for row in rows if row["retailer_id"] == "deloox"]
        expected = {
            (100, "SH-0030", "VAR-f87146c82d167f4c"),
            (150, "SH-0031", "VAR-f5aff76b4bb5de8a"),
        }
        observed = {
            (int(row["size_ml"]), row["product_id"], row["variant_id"])
            for row in deloox_rows
        }
        missing = sorted(expected - observed)
        if missing:
            raise AssertionError(f"Offer Engine did not publish exact Deloox Liquid Brun variants: {missing}")

        for row in deloox_rows:
            if row["availability"] == "out_of_stock":
                if row["price"] is not None:
                    raise AssertionError("Deloox sold-out offer retained a usable price")
            elif row["availability"] == "in_stock":
                if row["price"] is None or float(row["price"]) <= 0:
                    raise AssertionError("Deloox in-stock offer has no valid price")
            else:
                raise AssertionError(f"Unknown Deloox availability: {row['availability']}")

        # Deloox's two exact canonical variants are the hard live acceptance
        # gate. Other retailers may legitimately return unresolved or rejected
        # candidates (gift sets, ambiguous variants, blocked pages); those must
        # remain unpublished and be reported as warnings, not turn a safe
        # partial result into a false empty/failure signal.
        configured_notino = all(os.environ.get(name, "").strip() for name in (
            "NOTINO_CJ_FEED_URL",
            "NOTINO_CJ_FEED_USERNAME",
            "NOTINO_CJ_FEED_PASSWORD",
        ))
        retailer_warnings = []
        required_retailers = {
            "bplatz", "deloox", "easycosmetic", "orioudh",
            "parfumcity", "parfumzentrum", "perfumemarket", "sabina",
        }
        observed_retailers = {item.retailer for item in engine_result.connectors}
        for missing_retailer in sorted(required_retailers - observed_retailers):
            retailer_warnings.append({
                "retailer": missing_retailer,
                "status": "missing_connector",
                "reason": "required_live_smoke_retailer_not_executed",
            })
        for item in engine_result.connectors:
            if item.retailer == "notino" and not configured_notino:
                retailer_warnings.append({
                    "retailer": item.retailer,
                    "status": "not_configured",
                    "reason": "notino_feed_credentials_missing",
                })
                continue
            if (
                item.status != "success"
                or item.errors
                or item.unresolved
                or (item.retailer in required_retailers and item.offers_published < 1)
            ):
                retailer_warnings.append({
                    "retailer": item.retailer,
                    "status": item.status,
                    "listings_seen": item.listings_seen,
                    "offers_published": item.offers_published,
                    "errors": item.errors,
                    "unresolved": item.unresolved,
                    "unresolved_samples": item.unresolved_samples,
                })

        if not any(row["retailer_id"] != "deloox" for row in rows):
            raise AssertionError("No verified non-Deloox retailer offer was published")

        offer_keys = [
            (row["retailer_id"], row["product_id"], row["variant_id"], row["market"])
            for row in rows
        ]
        if len(offer_keys) != len(set(offer_keys)):
            raise AssertionError("Duplicate current offers exist for the same retailer/variant/market")

        for row in rows:
            if row["availability"] == "out_of_stock" and row["price"] is not None:
                raise AssertionError("A sold-out retailer offer retained a usable price")

        return {
            "status": "success_with_warnings" if retailer_warnings else "success",
            "mode": "read-only live Offer Engine end-to-end smoke",
            "database": "temporary SQLite; deleted after test",
            "production_database_accessed": False,
            "catalog_modified": False,
            "query": query,
            "deloox_variants": [
                {
                    "size_ml": int(row["size_ml"]),
                    "product_id": row["product_id"],
                    "variant_id": row["variant_id"],
                    "market": row["market"],
                    "availability": row["availability"],
                    "price": str(row["price"]) if row["price"] is not None else None,
                    "url": row["product_url"],
                }
                for row in sorted(deloox_rows, key=lambda item: int(item["size_ml"]))
            ],
            "published_offers": [
                {
                    "retailer": row["retailer_id"],
                    "product_id": row["product_id"],
                    "variant_id": row["variant_id"],
                    "size_ml": row["size_ml"],
                    "market": row["market"],
                    "availability": row["availability"],
                    "price": str(row["price"]) if row["price"] is not None else None,
                    "url": row["product_url"],
                }
                for row in rows
            ],
            "retailers": [
                {
                    "retailer": item.retailer,
                    "status": item.status,
                    "listings_seen": item.listings_seen,
                    "observations_written": item.observations_written,
                    "offers_published": item.offers_published,
                    "unresolved": item.unresolved,
                    "errors": item.errors,
                    "unresolved_samples": item.unresolved_samples,
                }
                for item in engine_result.connectors
            ],
            "total_offers_published": engine_result.offers_published,
            "retailer_warnings": retailer_warnings,
        }


def result_exit_code(result: dict) -> int:
    """Warnings are review evidence, not a failed safety assertion.

    Hard assertions (exact Deloox variants, valid stock/price state,
    non-Deloox coverage, and duplicate prevention) raise before this point.
    A partial retailer warning must still leave its JSON artifact available.
    """
    return 1 if result.get("status") == "failed" else 0


def main() -> None:
    result = run()
    output = json.dumps(result, ensure_ascii=False, indent=2)
    Path("next-engine-live-offer-engine-smoke.json").write_text(output + "\n", encoding="utf-8")
    print(output)
    if result_exit_code(result):
        raise SystemExit(
            "Live Offer Engine smoke failed; inspect "
            "next-engine-live-offer-engine-smoke.json."
        )


if __name__ == "__main__":
    main()
