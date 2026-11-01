"""Regression tests for the Phase 0 read-only baseline CSV."""
import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.scenthunter_next_engine.baseline_report import generate


class BaselineReportTests(unittest.TestCase):
    def test_generates_complete_csv_and_keeps_sqlite_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "product_catalog.json"
            catalog.write_text(json.dumps({
                "products": [{
                    "product_id": "P1",
                    "brand_name": "Dior",
                    "canonical_name": "Sauvage",
                    "aliases": ["Dior Sauvage"],
                }],
                "variants": [{
                    "variant_id": "V1",
                    "product_id": "P1",
                    "size_ml": 100,
                    "aliases": ["100 ml"],
                }],
            }), encoding="utf-8")
            db = root / "store_catalog.sqlite3"
            conn = sqlite3.connect(db)
            conn.execute("""CREATE TABLE store_product_variants (
                store TEXT, variant_url TEXT, url TEXT, name TEXT, brand TEXT,
                sku TEXT, gtin TEXT, size_ml REAL, concentration TEXT,
                price REAL, currency TEXT, availability TEXT, variant_key TEXT
            )""")
            conn.execute("""INSERT INTO store_product_variants VALUES (
                'deloox', 'https://shop.example/p1', 'https://shop.example/p1',
                'Dior Sauvage Eau de Parfum 100 ml', 'Dior', 'SKU1', '1234567890123',
                100, 'EDP', 89.9, 'EUR', 'in_stock', 'edp-100'
            )""")
            conn.commit()
            conn.close()
            output = root / "baseline.csv"

            summary = generate(catalog, db, output)

            self.assertEqual(summary["catalog_products"], 1)
            self.assertEqual(summary["catalog_variants"], 1)
            self.assertEqual(summary["offers"], 1)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["store"], "deloox")
            self.assertEqual(rows[0]["offer_count"], "1")
            self.assertIn("catalog_variant_count", rows[0])
            self.assertEqual(rows[0]["catalog_variant_count"], "1")
            self.assertEqual(rows[-1]["store"], "TOTAL")

            # Opening the DB in read-only mode must not alter its bytes.
            before = db.read_bytes()
            readonly = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            readonly.execute("PRAGMA query_only=ON")
            with self.assertRaises(sqlite3.OperationalError):
                readonly.execute("DELETE FROM store_product_variants")
            readonly.close()
            self.assertEqual(db.read_bytes(), before)

    def test_currency_validation_accepts_iso_style_codes_not_only_eur(self):
        from backend.scenthunter_next_engine.baseline_report import _valid_price
        self.assertTrue(_valid_price("10.50", "CHF"))
        self.assertTrue(_valid_price("10.50", "EUR"))
        self.assertFalse(_valid_price("10.50", "EU"))
        self.assertFalse(_valid_price("0", "EUR"))
        self.assertFalse(_valid_price("-1", "EUR"))


if __name__ == "__main__":
    unittest.main()
