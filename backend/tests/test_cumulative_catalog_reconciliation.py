"""Regression tests for the cumulative requested-brand catalog merge."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

class CumulativeCatalogReconciliationTests(unittest.TestCase):
    def test_catalog_has_unique_product_and_variant_ids(self):
        products = CATALOG["products"]
        variants = CATALOG["variants"]
        product_ids = [p["product_id"] for p in products]
        variant_ids = [v["variant_id"] for v in variants]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))

    def test_brand_canonical_identities_are_unique(self):
        keys = [(p.get("brand") or p.get("brand_name"), p["canonical_name"]) for p in CATALOG["products"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_all_variants_have_a_known_parent_product(self):
        product_ids = {p["product_id"] for p in CATALOG["products"]}
        self.assertTrue(all(v["product_id"] in product_ids for v in CATALOG["variants"]))

    def test_requested_brand_reconciliations_are_preserved(self):
        expected = {"Bujairami": 671, "Khadlaj": 227, "Games of Spades": 30, "Paris Corner": 259, "Velixir": 28}
        actual = {}
        for p in CATALOG["products"]:
            brand = p.get("brand") or p.get("brand_name")
            actual[brand] = actual.get(brand, 0) + 1
        for brand, count in expected.items():
            with self.subTest(brand=brand):
                self.assertEqual(actual.get(brand), count)

    def test_registry_family_product_names_are_unique(self):
        for family in REGISTRY["families"]:
            names = [p["canonical_name"] for p in family["products"]]
            with self.subTest(family=family["family_id"]):
                self.assertEqual(len(names), len(set(names)))

if __name__ == "__main__":
    unittest.main()
