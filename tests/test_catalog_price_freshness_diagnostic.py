"""Regression tests for aggregate, read-only catalog price freshness diagnostics."""

import sqlite3

from backend.catalog_engine import catalog_price_freshness_snapshot


def test_catalog_price_freshness_snapshot_aggregates_store_coverage_and_age_buckets():
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

    assert snapshot["read_only"] is True
    assert snapshot["writes_database"] is False
    assert snapshot["network_requests"] is False
    assert snapshot["thresholds_seconds"] == {
        "missing_price_retry": 6 * 60 * 60,
        "stale_price": 24 * 60 * 60,
    }
    assert shop["active_urls"] == 10
    assert shop["product_rows"] == 5
    assert shop["product_rows_vs_active_urls_pct"] == 50.0
    assert shop["priced_rows"] == 2
    assert shop["priced_share_pct"] == 40.0
    assert shop["missing_price_rows"] == 3
    assert shop["missing_price_retry_due_6h"] == 2
    assert shop["priced_fresh_24h"] == 1
    assert shop["priced_stale_24h"] == 1
    assert shop["fetch_age_buckets"] == {
        "under_6h": 2,
        "6_to_24h": 1,
        "24_to_72h": 1,
        "over_72h_or_null": 1,
    }
    assert shop["non_ok_fetch_rows"] == 1
    assert shop["variants"] == {
        "variant_rows": 2,
        "priced_variant_rows": 1,
        "priced_variants_stale_24h": 1,
    }
    assert shop["hydration_queue"] == {"DONE": 1, "PENDING": 2}


def test_price_freshness_endpoint_uses_read_only_database_connection():
    from pathlib import Path

    source = Path("backend/main.py").read_text(encoding="utf-8")
    route = source.split(
        "def diagnose_catalog_price_freshness_read_only():", 1
    )[1].split("@app.get('/diagnose-catalog-live-parse')", 1)[0]

    assert "as_uri() + '?mode=ro'" in route
    assert "PRAGMA query_only=ON" in route
    assert "catalog_price_freshness_snapshot(conn)" in route
    assert "refresh_url(" not in route
    assert "catalog_discover_store(" not in route
