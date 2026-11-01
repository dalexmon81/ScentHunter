"""Regression tests for the Phase 0 summary CSV."""
import csv
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scenthunter_next_engine.baseline_summary_report import ACTIVE_STORES, _rows, generate


class Phase0SummaryReportTests(unittest.TestCase):
    def _fixture(self, directory):
        root = Path(directory)
        catalog = root / "product_catalog.json"
        catalog.write_text(json.dumps({
            "products": [{
                "product_id": "p1",
                "brand_name": "Acme",
                "canonical_name": "Alpha",
                "aliases": [],
            }],
            "variants": [],
        }), encoding="utf-8")
        db = root / "store_catalog.sqlite3"
        conn = sqlite3.connect(db)
        conn.executescript("""
            CREATE TABLE store_products (
                store TEXT, url TEXT, name TEXT, brand TEXT, sku TEXT, gtin TEXT,
                size_ml REAL, concentration TEXT, price REAL, currency TEXT,
                availability TEXT
            );
            CREATE TABLE store_urls (
                store TEXT, url TEXT, slug TEXT, lastmod TEXT,
                discovered_at REAL, active INTEGER
            );
        """)
        for store in ACTIVE_STORES:
            url = f"https://{store}.example/alpha"
            conn.execute(
                "INSERT INTO store_urls VALUES (?, ?, ?, NULL, 1800000000, 1)",
                (store, url, "alpha"),
            )
            if store != "notino":
                conn.execute(
                    "INSERT INTO store_products VALUES (?, ?, ?, ?, NULL, NULL, 100, 'edp', 25, 'EUR', 'in_stock')",
                    (store, url, "Alpha", "Acme"),
                )
        conn.execute(
            "INSERT INTO store_urls VALUES ('amazon_de', 'https://amazon.example/x', 'x', NULL, 1800000000, 1)"
        )
        conn.commit()
        conn.close()
        return catalog, db

    def test_nine_store_csv_includes_notino_with_zero_offers(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog, db = self._fixture(directory)
            output = Path(directory) / "summary.csv"
            summary = generate(catalog, db, output)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

        by_store = {row["store"]: row for row in rows}
        self.assertEqual(summary["stores"], 9)
        self.assertEqual(set(by_store), set(ACTIVE_STORES) | {"TOTAL"})
        self.assertEqual(by_store["notino"]["indexed_url_count"], "1")
        self.assertEqual(by_store["notino"]["offer_count"], "0")
        self.assertEqual(by_store["notino"]["valid_price_pct"], "0")
        self.assertNotIn("amazon_de", by_store)
        self.assertNotIn("amazon_fr", by_store)

    def test_indexed_url_count_is_distinct_and_active_only(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog, db = self._fixture(directory)
            conn = sqlite3.connect(db)
            conn.execute(
                "INSERT INTO store_urls VALUES ('notino', 'https://notino.example/alpha', 'duplicate', NULL, 1800000000, 1)"
            )
            conn.execute(
                "INSERT INTO store_urls VALUES ('notino', 'https://notino.example/inactive', 'inactive', NULL, 1800000000, 0)"
            )
            conn.commit()
            conn.close()
            output = Path(directory) / "summary.csv"
            generate(catalog, db, output)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        notino = next(row for row in rows if row["store"] == "notino")
        self.assertEqual(notino["indexed_url_count"], "2")


if __name__ == "__main__":
    unittest.main()
