"""Regression tests for the Phase 0 retailer baseline report."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scenthunter_next_engine.baseline_report import ACTIVE_STORES, _rows


def test_baseline_keeps_notino_indexed_urls_without_fabricating_offers():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE store_product_variants (
            store TEXT, variant_url TEXT, url TEXT, name TEXT, brand TEXT,
            sku TEXT, gtin TEXT, size_ml REAL, concentration TEXT,
            price REAL, currency TEXT, availability TEXT,
            variant_key TEXT
        );
        CREATE TABLE store_products (
            store TEXT, url TEXT, name TEXT, brand TEXT, sku TEXT, gtin TEXT,
            size_ml REAL, concentration TEXT, price REAL, currency TEXT,
            availability TEXT
        );
        CREATE TABLE store_urls (
            store TEXT, url TEXT, slug TEXT, lastmod TEXT,
            discovered_at INTEGER, active INTEGER
        );
        INSERT INTO store_products VALUES (
            'bplatz', 'https://bplatz.example/item', 'Example Product',
            'Example', NULL, NULL, 100, 'eau de parfum', 50, 'EUR', 'in_stock'
        );
        INSERT INTO store_urls VALUES (
            'notino', 'https://www.notino.fr/product/one', 'one', NULL, 1800000000, 1
        );
        INSERT INTO store_urls VALUES (
            'notino', 'https://www.notino.fr/product/two', 'two', NULL, 1800000000, 1
        );
        INSERT INTO store_urls VALUES (
            'amazon_de', 'https://www.amazon.de/dp/B000000000', 'amazon', NULL, 1800000000, 1
        );
        """
    )

    rows, source, indexed_urls = _rows(conn)
    conn.close()

    assert len(ACTIVE_STORES) == 9
    assert {row["store"] for row in rows} == {"bplatz"}
    assert indexed_urls["notino"] == 2
    assert "amazon_de" not in indexed_urls
