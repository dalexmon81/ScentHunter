"""Read-only live end-to-end smoke test for the isolated Offer Engine.

Uses a temporary SQLite database only. It never connects to or mutates the
production database or canonical catalog.
"""
from __future__ import annotations

import json
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

        return {
            "status": "success",
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
        }


def main() -> None:
    result = run()
    output = json.dumps(result, ensure_ascii=False, indent=2)
    Path("next-engine-live-offer-engine-smoke.json").write_text(output + "\\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
