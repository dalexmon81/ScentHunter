"""Regression tests for French Avenue official product identity additions."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Jasmere": "https://frenchavenue.com/products/jasmere",
    "Amber Empire": "https://frenchavenue.com/products/amber-empire",
    "Safari Breeze": "https://sa.frenchavenue.com/products/safari-breeze",
}


class FrenchAvenueCatalogTests(unittest.TestCase):
    def test_official_fragrance_identities_and_sources_exist(self):
        products = {
            p["canonical_name"]: p for p in CATALOG["products"]
            if p.get("brand") == "French Avenue"
        }
        for name, url in EXPECTED.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                self.assertEqual(products[name]["source_url"], url)
                self.assertEqual(products[name]["identity_status"], "source_verified_name")

    def test_family_registry_matches_new_catalog_identities(self):
        family = next(
            f for f in REGISTRY["families"]
            if f["family_id"] == "french_avenue_catalog"
        )
        names = {p["canonical_name"] for p in family["products"]}
        self.assertTrue(set(EXPECTED).issubset(names))

    def test_product_ids_and_brand_name_pairs_are_unique(self):
        products = CATALOG["products"]
        ids = [p["product_id"] for p in products]
        pairs = [
            (p.get("brand") or p.get("brand_name"), p.get("canonical_name") or p.get("name"))
            for p in products
        ]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_no_commercial_offer_fields_were_added(self):
        for product in CATALOG["products"]:
            if product.get("brand") == "French Avenue" and product.get("canonical_name") in EXPECTED:
                for field in ("price", "stock", "availability", "shipping_cost", "store_url", "gtin"):
                    self.assertNotIn(field, product)


if __name__ == "__main__":
    unittest.main()
