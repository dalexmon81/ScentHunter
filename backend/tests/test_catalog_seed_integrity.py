"""Regression checks for the catalog-first fragrance identity seed.

Run locally from the repository root:
    python -m unittest discover -s backend/tests -p 'test_catalog_seed_integrity.py'

These checks validate catalog data only. They do not test live ingestion,
retailer pricing, matching quality, or deployed services.
"""
import json
import unittest
from pathlib import Path


CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"


class CatalogSeedIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = cls.catalog["products"]
        cls.variants = cls.catalog["variants"]
        cls.products_by_id = {p["product_id"]: p for p in cls.products}

    def test_canonical_product_ids_are_unique(self):
        ids = [p["product_id"] for p in self.products]
        self.assertEqual(len(ids), len(set(ids)))

    def test_canonical_products_have_required_identity_fields(self):
        for product in self.products:
            with self.subTest(product_id=product.get("product_id")):
                for field in ("product_id", "brand", "canonical_name"):
                    self.assertIsInstance(product.get(field), str)
                    self.assertTrue(product[field].strip())

    def test_variants_reference_existing_products(self):
        for variant in self.variants:
            with self.subTest(variant=variant):
                self.assertIn(variant["product_id"], self.products_by_id)

    def test_variant_sizes_are_positive_numbers(self):
        for variant in self.variants:
            with self.subTest(variant=variant):
                size = variant.get("size_ml")
                self.assertIsInstance(size, (int, float))
                self.assertNotIsInstance(size, bool)
                self.assertGreater(size, 0)

    def test_no_duplicate_product_size_variant(self):
        keys = [(v["product_id"], v["size_ml"]) for v in self.variants]
        self.assertEqual(len(keys), len(set(keys)))

    def test_variant_sizes_appear_in_parent_product_formats(self):
        for variant in self.variants:
            product = self.products_by_id[variant["product_id"]]
            with self.subTest(product=product["canonical_name"], size=variant["size_ml"]):
                self.assertIn(variant["size_ml"], product.get("formats_ml", []))

    def test_known_multi_size_variant_does_not_collapse(self):
        products = [
            p for p in self.products
            if p["brand"] == "Afnan"
            and p["canonical_name"] == "Supremacy Not Only Intense"
        ]
        self.assertEqual(len(products), 1)
        sizes = {
            v["size_ml"] for v in self.variants
            if v["product_id"] == products[0]["product_id"]
        }
        self.assertTrue({100, 150}.issubset(sizes))

    def test_variants_are_not_offers(self):
        for variant in self.variants:
            with self.subTest(variant=variant):
                for offer_field in ("price", "stock", "shipping_cost", "store_url"):
                    self.assertNotIn(offer_field, variant)


if __name__ == "__main__":
    unittest.main()
