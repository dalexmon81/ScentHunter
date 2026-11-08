"""Regression tests for official Lattafa identity additions."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


class LattafaCatalogTests(unittest.TestCase):
    def test_official_product_page_identities_exist(self):
        products = {
            p["canonical_name"]: p for p in CATALOG["products"]
            if p.get("brand") == "Lattafa"
        }
        for name, url in {
            "Queen of Arabia": "https://lattafa.com/product/queen-of-arabia/",
            "Musamam Black Intense": "https://lattafa.com/product/musamam-black-intense/",
        }.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                self.assertEqual(products[name]["source_url"], url)
                self.assertEqual(products[name]["identity_status"], "source_verified_name")

    def test_lattta_family_registry_contains_both_names(self):
        family = next(f for f in REGISTRY["families"] if f["brand"] == "Lattafa")
        names = {p["canonical_name"] for p in family["products"]}
        self.assertTrue({"Queen of Arabia", "Musamam Black Intense"}.issubset(names))

    def test_no_duplicate_ids_or_brand_name_pairs(self):
        products = CATALOG["products"]
        ids = [p["product_id"] for p in products]
        pairs = [(p.get("brand") or p.get("brand_name"), p.get("canonical_name") or p.get("name")) for p in products]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_no_offer_or_unverified_variant_fields_added(self):
        for p in CATALOG["products"]:
            if p.get("canonical_name") in {"Queen of Arabia", "Musamam Black Intense"} and p.get("brand") == "Lattafa":
                for field in ("price", "stock", "availability", "shipping_cost", "store_url"):
                    self.assertNotIn(field, p)


if __name__ == "__main__":
    unittest.main()
