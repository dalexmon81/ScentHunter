import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scenthunter_next_engine.baseline_report import (
    BaselineIncompleteError,
    COLUMNS,
    SUPPORTED_STORES,
    generate,
)


class Phase0BaselineReportTests(unittest.TestCase):
    def _fixture(self, directory, include_all=True):
        root = Path(directory)
        catalog_path = root / "product_catalog.json"
        catalog_path.write_text(json.dumps({
            "products": [{
                "product_id": "p1",
                "brand_name": "Acme",
                "canonical_name": "Alpha",
                "aliases": [],
                "concentration": "Eau de Parfum",
            }],
            "variants": [{
                "variant_id": "v1",
                "product_id": "p1",
                "size_ml": 100,
                "aliases": ["Alpha 100 ml"],
            }],
        }), encoding="utf-8")

        db_path = root / "store_catalog.sqlite3"
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE store_urls (
                store TEXT, url TEXT, slug TEXT, lastmod TEXT,
                discovered_at REAL, active INTEGER DEFAULT 1
            );
            CREATE TABLE store_products (
                store TEXT, url TEXT, name TEXT, brand TEXT, image TEXT,
                sku TEXT, gtin TEXT, mpn TEXT, size_ml REAL, concentration TEXT,
                gender TEXT, price REAL, currency TEXT, availability TEXT,
                fetched_at REAL, fetch_status TEXT
            );
            CREATE TABLE store_product_variants (
                store TEXT, url TEXT, variant_key TEXT, name TEXT, brand TEXT,
                image TEXT, sku TEXT, gtin TEXT, mpn TEXT, size_ml REAL,
                concentration TEXT, gender TEXT, price REAL, currency TEXT,
                availability TEXT, fetched_at REAL, variant_url TEXT
            );
        """)
        stores = SUPPORTED_STORES if include_all else tuple(
            store for store in SUPPORTED_STORES if store != "notino"
        )
        for index, store in enumerate(stores):
            url = f"https://{store}.test/alpha"
            conn.execute(
                "INSERT INTO store_urls VALUES (?, ?, ?, ?, ?, 1)",
                (store, url, "alpha", None, 1_800_000_000),
            )
            if store == "bplatz":
                conn.execute(
                    """INSERT INTO store_products VALUES
                       (?, ?, 'Alpha 100 ml', 'Acme', NULL, 'sku-1', NULL,
                        NULL, 100, 'Eau de Parfum', NULL, 12.5, 'EUR',
                        'in_stock', 1800000000, 'OK')""",
                    (store, url),
                )
                conn.execute(
                    """INSERT INTO store_product_variants VALUES
                       (?, ?, 'v1', 'Alpha 100 ml', 'Acme', NULL, 'sku-1',
                        NULL, NULL, 100, 'Eau de Parfum', NULL, 12.5, 'EUR',
                        'in_stock', 1800000000, ?)""",
                    (store, url, url + "/100ml"),
                )
                # Duplicate representation of the same offer must be removed.
                conn.execute(
                    """INSERT INTO store_product_variants VALUES
                       (?, ?, 'v1-duplicate', 'Alpha 100 ml', 'Acme', NULL,
                        'sku-1', NULL, NULL, 100, 'Eau de Parfum', NULL,
                        12.5, 'EUR', 'in_stock', 1800000000, ?)""",
                    (store, url, url + "/100ml"),
                )
            else:
                conn.execute(
                    """INSERT INTO store_products VALUES
                       (?, ?, 'Alpha 100 ml', 'Acme', NULL, ?, NULL, NULL,
                        100, 'Eau de Parfum', NULL, 12.5, 'EUR', 'in_stock',
                        1800000000, 'OK')""",
                    (store, url, f"sku-{index}"),
                )
        conn.commit()
        conn.close()
        return catalog_path, db_path

    def test_exports_offer_level_rows_for_all_nine_active_stores_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog_path, db_path = self._fixture(directory)
            output = Path(directory) / "baseline.csv"
            summary = generate(catalog_path, db_path, output)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)

            self.assertEqual(tuple(reader.fieldnames), COLUMNS)
            self.assertTrue({
                "store", "canonical_product_id", "brand", "fragrance",
                "concentration", "size_ml", "variant_type", "gtin",
                "external_product_id", "offer_url", "price", "currency",
                "availability", "captured_at", "source", "match_confidence",
                "is_valid_offer",
            }.issubset(set(reader.fieldnames)))
            self.assertEqual({row["store"] for row in rows}, set(SUPPORTED_STORES))
            self.assertEqual(len(rows), 9)
            self.assertEqual(summary["stores"], 9)
            self.assertEqual(summary["excluded_stores"], ["amazon_de", "amazon_fr"])
            self.assertNotIn("amazon_de", {row["store"] for row in rows})
            self.assertNotIn("amazon_fr", {row["store"] for row in rows})
            self.assertEqual(summary["offers"], 9)
            self.assertEqual(summary["duplicate_rows_skipped"], 1)
            bplatz = next(row for row in rows if row["store"] == "bplatz")
            self.assertEqual(bplatz["canonical_product_id"], "p1")
            self.assertEqual(bplatz["canonical_variant_id"], "v1")
            self.assertEqual(bplatz["variant_type"], "retailer_variant")
            self.assertEqual(bplatz["match_confidence"], "1.0")
            self.assertEqual(bplatz["is_valid_offer"], "true")

    def test_refuses_partial_baseline_when_any_required_store_has_no_offers(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog_path, db_path = self._fixture(directory, include_all=False)
            output = Path(directory) / "baseline.csv"
            with patch(
                "scenthunter_next_engine.baseline_report._catalog_matcher",
                side_effect=AssertionError("canonical indexing must not run for an incomplete baseline"),
            ), patch(
                "scenthunter_next_engine.baseline_report._match",
                side_effect=AssertionError("matching must not run for an incomplete baseline"),
            ):
                with self.assertRaises(BaselineIncompleteError) as raised:
                    generate(catalog_path, db_path, output)
            self.assertIn("notino", str(raised.exception))
            self.assertFalse(output.exists())

    def test_refuses_baseline_when_active_store_has_no_fully_valid_offer(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog_path, db_path = self._fixture(directory)
            conn = sqlite3.connect(db_path)
            conn.execute(
                "UPDATE store_products SET availability='unknown' WHERE store='notino'"
            )
            conn.commit()
            conn.close()
            output = Path(directory) / "baseline.csv"
            with self.assertRaises(BaselineIncompleteError) as raised:
                generate(catalog_path, db_path, output)
            self.assertIn("fully valid offer", str(raised.exception))
            self.assertIn("notino", str(raised.exception))
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
