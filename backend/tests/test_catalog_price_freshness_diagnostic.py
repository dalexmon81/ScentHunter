"""Regression tests for aggregate, read-only catalog price freshness diagnostics."""

import sqlite3
import unittest
from pathlib import Path

from catalog_engine import catalog_price_freshness_snapshot


class CatalogPriceFreshnessDiagnosticTests(unittest.TestCase):
    def test_snapshot_aggregates_store_coverage_and_age_buckets(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE store_products (
                store TEXT, price REAL, fetched_at REAL, fetch_status TEXT
            );
            CREATE TABLE store_urls (store TEXT, active INTEGER);
            CREATE TABLE store_product_variants (
                store TEXT, price REAL, fetched_at REAL
            );
            CREATE TABLE hydration_queue (store TEXT, state TEXT);
            """
        )
        now = 1_000_000.0
        conn.executemany(
            "INSERT INTO store_products(store, price, fetched_at, fetch_status) VALUES(?,?,?,?)",
            [
                ("shop_a", 20.0, now - 3600, "OK"),
                ("shop_a", 18.0, now - 30 * 3600, "OK"),
                ("shop_a", None, now - 8 * 3600, "ERROR"),
                ("shop_a", None, now - 2 * 3600, "OK"),
                ("shop_a", 0.0, None, None),
            ],
        )
        conn.executemany(
            "INSERT INTO store_urls(store, active) VALUES(?,?)",
            [("shop_a", 1)] * 10 + [("shop_a", 0)],
        )
        conn.executemany(
            "INSERT INTO store_product_variants(store, price, fetched_at) VALUES(?,?,?)",
            [
                ("shop_a", 12.0, now - 50 * 3600),
                ("shop_a", None, now - 2 * 3600),
            ],
        )
        conn.executemany(
            "INSERT INTO hydration_queue(store, state) VALUES(?,?)",
            [("shop_a", "PENDING"), ("shop_a", "PENDING"), ("shop_a", "DONE")],
        )

        snapshot = catalog_price_freshness_snapshot(conn, now=now)
        shop = snapshot["stores"]["shop_a"]

        self.assertTrue(snapshot["read_only"])
        self.assertFalse(snapshot["writes_database"])
        self.assertFalse(snapshot["network_requests"])
        self.assertEqual(snapshot["thresholds_seconds"], {
            "missing_price_retry": 6 * 60 * 60,
            "stale_price": 24 * 60 * 60,
        })
        self.assertEqual(shop["active_urls"], 10)
        self.assertEqual(shop["product_rows"], 5)
        self.assertEqual(shop["product_rows_vs_active_urls_pct"], 50.0)
        self.assertEqual(shop["priced_rows"], 2)
        self.assertEqual(shop["priced_share_pct"], 40.0)
        self.assertEqual(shop["missing_price_rows"], 3)
        self.assertEqual(shop["missing_price_retry_due_6h"], 2)
        self.assertEqual(shop["priced_fresh_24h"], 1)
        self.assertEqual(shop["priced_stale_24h"], 1)
        self.assertEqual(shop["fetch_age_buckets"], {
            "under_6h": 2,
            "6_to_24h": 1,
            "24_to_72h": 1,
            "over_72h_or_null": 1,
        })
        self.assertEqual(shop["non_ok_fetch_rows"], 1)
        self.assertEqual(shop["variants"], {
            "variant_rows": 2,
            "priced_variant_rows": 1,
            "priced_variants_stale_24h": 1,
        })
        self.assertEqual(shop["hydration_queue"], {"DONE": 1, "PENDING": 2})
        conn.close()

    def test_endpoint_uses_read_only_database_connection(self):
        source = Path("main.py").read_text(encoding="utf-8")
        route = source.split(
            "def diagnose_catalog_price_freshness_read_only():", 1
        )[1].split("@app.get('/diagnose-catalog-live-parse')", 1)[0]

        self.assertIn("as_uri() + '?mode=ro'", route)
        self.assertIn("PRAGMA query_only=ON", route)
        self.assertIn("catalog_price_freshness_snapshot(conn)", route)
        self.assertNotIn("refresh_url(", route)
        self.assertNotIn("catalog_discover_store(", route)


if __name__ == "__main__":
    unittest.main()
