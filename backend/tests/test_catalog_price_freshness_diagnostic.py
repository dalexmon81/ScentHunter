"""Regression tests for aggregate, read-only catalog price freshness diagnostics."""

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import catalog_engine
from catalog_engine import (
    _catalog_row_needs_refresh,
    catalog_price_freshness_snapshot,
    prioritize_hydration_candidates,
)


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

    def test_refresh_due_respects_six_and_twenty_four_hour_thresholds(self):
        now = 1_800_000_000.0
        self.assertFalse(_catalog_row_needs_refresh(25.0, now - 23 * 60 * 60, now=now))
        self.assertTrue(_catalog_row_needs_refresh(25.0, now - 25 * 60 * 60, now=now))
        self.assertFalse(_catalog_row_needs_refresh(None, now - 5 * 60 * 60, now=now))
        self.assertTrue(_catalog_row_needs_refresh(None, now - 7 * 60 * 60, now=now))
        self.assertTrue(_catalog_row_needs_refresh(0, now - 7 * 60 * 60, now=now))

    def test_search_priority_requeues_only_due_done_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "catalog.sqlite3"
            conn = sqlite3.connect(database_path)
            conn.executescript(
                """
                CREATE TABLE hydration_queue (
                    store TEXT, url TEXT, state TEXT, priority INTEGER DEFAULT 100,
                    attempts INTEGER DEFAULT 0, available_at REAL DEFAULT 0,
                    first_seen_at REAL DEFAULT 0, PRIMARY KEY(store,url)
                );
                CREATE TABLE store_urls (
                    store TEXT, url TEXT, active INTEGER, PRIMARY KEY(store,url)
                );
                CREATE TABLE store_products (
                    store TEXT, url TEXT, price REAL, fetched_at REAL,
                    fetch_status TEXT, PRIMARY KEY(store,url)
                );
                """
            )
            now = time.time()
            cases = [
                ("stale-priced", 25.0, now - 30 * 60 * 60, 1),
                ("stale-missing", None, now - 8 * 60 * 60, 1),
                ("fresh-priced", 25.0, now - 2 * 60 * 60, 1),
                ("fresh-base-stale-variant", 25.0, now - 2 * 60 * 60, 1),
                ("fresh-missing", None, now - 2 * 60 * 60, 1),
                ("inactive-stale", 25.0, now - 30 * 60 * 60, 0),
            ]
            for slug, price, fetched_at, active in cases:
                url = f"https://en.bplatz.de/products/{slug}"
                conn.execute(
                    "INSERT INTO hydration_queue(store,url,state,priority,available_at,first_seen_at) VALUES(?,?,?,?,?,?)",
                    ("bplatz", url, "DONE", 100, now + 3600, now),
                )
                conn.execute(
                    "INSERT INTO store_urls(store,url,active) VALUES(?,?,?)",
                    ("bplatz", url, active),
                )
                conn.execute(
                    "INSERT INTO store_products(store,url,price,fetched_at,fetch_status) VALUES(?,?,?,?,?)",
                    ("bplatz", url, price, fetched_at, "OK"),
                )
            conn.execute(
                "INSERT INTO store_product_variants(store,url,variant_key,price,fetched_at) VALUES(?,?,?,?,?)",
                (
                    "bplatz",
                    "https://en.bplatz.de/products/fresh-base-stale-variant",
                    "100ml:sku:variant",
                    12.0,
                    now - 30 * 60 * 60,
                ),
            )
            conn.commit()
            conn.close()

            canonical_stale_url = "https://en.bplatz.de/products/stale-priced"
            selected_rows = [
                {
                    "store_key": "bplatz",
                    "url": canonical_stale_url + "?variant=100ml",
                    "product_url": canonical_stale_url,
                    "_needs_refresh": True,
                }
            ] + [
                {
                    "store_key": "bplatz",
                    "url": f"https://en.bplatz.de/products/{slug}",
                    "_needs_refresh": True,
                }
                for slug, _price, _fetched_at, _active in cases[1:]
            ] + [
                {
                    "store_key": "bplatz",
                    "url": "https://en.bplatz.de/products/fresh-base-stale-variant?variant=100ml",
                    "product_url": "https://en.bplatz.de/products/fresh-base-stale-variant",
                    "_needs_refresh": True,
                }
            ]

            with patch.object(catalog_engine, "DB_PATH", database_path):
                updated = prioritize_hydration_candidates(selected_rows, priority=0)

            self.assertGreaterEqual(updated, 2)
            conn = sqlite3.connect(database_path)
            conn.row_factory = sqlite3.Row
            states = {
                row["url"].rsplit("/", 1)[-1]: dict(row)
                for row in conn.execute("SELECT url,state,priority,available_at FROM hydration_queue")
            }
            conn.close()

            self.assertEqual(states["stale-priced"]["state"], "PENDING")
            self.assertEqual(states["stale-missing"]["state"], "PENDING")
            self.assertEqual(states["stale-priced"]["priority"], 0)
            self.assertLessEqual(states["stale-priced"]["available_at"], time.time() + 1)
            self.assertEqual(states["fresh-priced"]["state"], "DONE")
            self.assertEqual(states["fresh-base-stale-variant"]["state"], "PENDING")
            self.assertEqual(states["fresh-missing"]["state"], "DONE")
            self.assertEqual(states["inactive-stale"]["state"], "DONE")

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
