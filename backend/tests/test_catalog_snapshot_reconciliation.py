"""Snapshot reconciliation guard for the requested-brand catalog baseline."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))


class CatalogSnapshotReconciliationTests(unittest.TestCase):
    def test_catalog_preserves_reconciled_identity_and_variant_baseline(self):
        products = CATALOG.get("products", [])
        variants = CATALOG.get("variants", [])
        self.assertGreaterEqual(len(products), 2061)
        self.assertGreaterEqual(len(variants), 291)

    def test_product_and_variant_ids_are_unique(self):
        products = CATALOG.get("products", [])
        variants = CATALOG.get("variants", [])
        product_ids = [row.get("product_id") for row in products]
        variant_ids = [row.get("variant_id") for row in variants]
        self.assertTrue(all(product_ids))
        self.assertTrue(all(variant_ids))
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))

    def test_variants_have_valid_parent_and_explicit_positive_size(self):
        products = {
            row.get("product_id"): row
            for row in CATALOG.get("products", [])
        }
        for index, variant in enumerate(CATALOG.get("variants", [])):
            with self.subTest(variant_index=index, variant_id=variant.get("variant_id")):
                parent = products.get(variant.get("product_id"))
                self.assertIsNotNone(parent, "orphan variant")
                size_ml = variant.get("size_ml")
                self.assertIsInstance(size_ml, int)
                self.assertGreater(size_ml, 0)
                self.assertTrue(parent.get("source_url"))

    def test_requested_brand_identity_baseline_is_preserved(self):
        expected_minimums = {
            "Velixir": 28, "Mykonos": 72, "Maison Asrar": 120,
            "Khadlaj": 116, "Bujairami": 142, "Paris Corner": 246,
            "Assaf": 140, "Al Wataniah": 86, "Armaf": 190,
            "French Avenue": 119, "Arabiyat Prestige": 118,
            "Gulf Orchid": 23, "Swiss Arabian": 32, "Games of Spades": 29,
            "Lattafa": 114, "Afnan": 87, "Aromatix": 12,
            "Maison Alhambra": 207, "Zimaya": 76, "Al Haramain": 101,
        }
        counts = {}
        for row in CATALOG.get("products", []):
            brand = str(row.get("brand_name") or row.get("brand") or "").strip()
            counts[brand] = counts.get(brand, 0) + 1
        for brand, minimum in expected_minimums.items():
            with self.subTest(brand=brand):
                self.assertGreaterEqual(counts.get(brand, 0), minimum)


if __name__ == "__main__":
    unittest.main()
