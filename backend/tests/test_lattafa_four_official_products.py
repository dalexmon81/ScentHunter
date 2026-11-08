"""Official product-page evidence for four Lattafa fragrances."""

import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
PRODUCTS = {
    "New York the City of Dreams": "https://lattafa.com/product/new-york-the-city-of-dreams/",
    "Love In Paris": "https://lattafa.com/product/love-in-paris/",
    "Raghad": "https://lattafa.com/product/raghad/",
    "Badee Al Oud Amethyst Fusion": "https://lattafa.com/product/badee-al-oud-amethyst-fusion/",
}


class LattafaFourOfficialProductsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = cls.catalog["products"]
        cls.variants = cls.catalog["variants"]

    def test_each_official_identity_is_unique_and_source_verified(self):
        for name, url in PRODUCTS.items():
            with self.subTest(product=name):
                matches = [
                    p for p in self.products
                    if p.get("brand_name") == "Lattafa"
                    and p.get("canonical_name") == name
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].get("identity_status"), "source_verified_name")
                self.assertEqual(matches[0].get("source_url"), url)
                self.assertEqual(matches[0].get("source_evidence_url"), url)

    def test_each_product_has_one_100ml_variant_without_inferred_concentration(self):
        for name in PRODUCTS:
            with self.subTest(product=name):
                product = next(
                    p for p in self.products
                    if p.get("brand_name") == "Lattafa"
                    and p.get("canonical_name") == name
                )
                variants = [
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                ]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("size_ml"), 100)
                self.assertNotIn("concentration", variants[0])
                for forbidden in ("price", "stock", "shipping_cost", "store_url"):
                    self.assertNotIn(forbidden, variants[0])

    def test_family_registry_and_variant_ids_remain_consistent(self):
        ids = [v.get("variant_id") for v in self.variants]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
