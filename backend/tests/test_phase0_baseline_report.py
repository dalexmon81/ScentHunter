import csv
import json
import sqlite3

from scenthunter_next_engine.baseline_report import SUPPORTED_STORES, generate


def test_generate_reports_all_eleven_stores_and_complete_quality_metrics(tmp_path):
    catalog_path = tmp_path / "product_catalog.json"
    catalog_path.write_text(
        json.dumps({
            "products": [{
                "product_id": "p1",
                "brand_name": "Acme",
                "canonical_name": "Alpha",
                "aliases": [],
                "concentration": "eau de parfum",
            }],
            "variants": [{
                "variant_id": "v1",
                "product_id": "p1",
                "size_ml": 100,
                "aliases": ["Alpha 100 ml"],
            }],
        }),
        encoding="utf-8",
    )

    db_path = tmp_path / "store_catalog.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE store_products (
            store TEXT, url TEXT, name TEXT, brand TEXT, sku TEXT, gtin TEXT,
            size_ml REAL, concentration TEXT, price REAL, currency TEXT,
            availability TEXT
        );
        CREATE TABLE store_product_variants (
            store TEXT, url TEXT, variant_url TEXT, variant_key TEXT,
            name TEXT, brand TEXT, sku TEXT, gtin TEXT, size_ml REAL,
            concentration TEXT, price REAL, currency TEXT, availability TEXT
        );
    """)
    conn.execute(
        """INSERT INTO store_products VALUES
           ('bplatz', 'https://shop.test/alpha', 'Alpha 100 ml', 'Acme',
            'sku-1', NULL, 100, 'eau de parfum', 12.5, 'EUR', 'in_stock')"""
    )
    conn.execute(
        """INSERT INTO store_product_variants VALUES
           ('bplatz', 'https://shop.test/alpha', 'https://shop.test/alpha-100',
            'v1', 'Alpha 100 ml', 'Acme', 'sku-1', NULL, 100,
            'eau de parfum', 12.5, 'EUR', 'in_stock')"""
    )
    conn.execute(
        """INSERT INTO store_products VALUES
           ('notino', 'not-a-url', 'Unknown item', 'Acme',
            'sku-2', NULL, 50, 'eau de parfum', NULL, 'EUR', 'unknown')"""
    )
    conn.commit()
    conn.close()

    output_path = tmp_path / "baseline.csv"
    summary = generate(catalog_path, db_path, output_path)

    with output_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(SUPPORTED_STORES) == 11
    assert {row["store"] for row in rows if row["store"] != "TOTAL"} == set(SUPPORTED_STORES)
    assert rows[-1]["store"] == "TOTAL"
    assert summary["stores"] == 11
    assert summary["catalog_products"] == 1
    assert summary["offers"] == 2

    by_store = {row["store"]: row for row in rows}
    assert by_store["bplatz"]["offer_count"] == "1"
    assert by_store["bplatz"]["valid_price_pct"] == "100.0"
    assert by_store["bplatz"]["valid_url_pct"] == "100.0"
    assert by_store["bplatz"]["valid_stock_pct"] == "100.0"
    assert by_store["notino"]["offer_count"] == "1"
    assert by_store["notino"]["valid_price_pct"] == "0"
    assert by_store["notino"]["valid_url_pct"] == "0"
    assert by_store["notino"]["valid_stock_pct"] == "0"
    assert by_store["amazon_de"]["offer_count"] == "0"
    assert by_store["TOTAL"]["offer_count"] == "2"
    assert by_store["TOTAL"]["catalog_product_count"] == "1"
