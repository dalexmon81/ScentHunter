"""Regression tests for two Armaf fragrances verified on official EU product pages."""

import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG_PATH = BACKEND / "product_catalog.json"
FAMILY_PATH = BACKEND / "family_registry.json"
PRODUCTS = {
    "Dunescape Dubai": (
        "https://armaf.eu/products/dunescape",
        "Extrait de Parfum",
    ),
    "Check Mate White Knight": (
        "https://cz.armaf.eu/en/products/check-mate-white-knight",
        "Eau de Parfum",
    ),
}


class ArmafOfficialEuHarvestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        with FAMILY_PATH.open(encoding="utf-8") as handle:
            registry = json.load(handle)
        cls.products = cls.catalog["products"]
        cls.variants = cls.catalog["variants"]
        cls.family = next(
            family for family in registry["families"]
            if family["family_id"] == "armaf_catalog"
        )

    def test_official_products_and_family_entries_are_unique(self):
        for name, (url, _) in PRODUCTS.items():
            with self.subTest(product=name):
                matches = [
                    product for product in self.products
                    if product.get("brand_name") == "Armaf"
                    and product.get("canonical_name") == name
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].get("identity_status"), "source_verified_name")
                self.assertEqual(matches[0].get("source_url"), url)
                family_matches = [
                    product for product in self.family["products"]
                    if product.get("canonical_name") == name
                ]
                self.assertEqual(len(family_matches), 1)

    def test_only_documented_size_and_concentration_are_recorded(self):
        for name, (_, concentration) in PRODUCTS.items():
            with self.subTest(product=name):
                product = next(
                    product for product in self.products
                    if product.get("brand_name") == "Armaf"
                    and product.get("canonical_name") == name
                )
                self.assertEqual(product.get("formats_ml"), [100])
                self.assertEqual(product.get("concentration"), concentration)
                variants = [
                    variant for variant in self.variants
                    if variant.get("product_id") == product["product_id"]
                ]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("size_ml"), 100)
                self.assertEqual(variants[0].get("concentration"), concentration)

    def test_product_and_variant_ids_are_unique_and_variants_have_parents(self):
        product_ids = [product.get("product_id") for product in self.products]
        variant_ids = [variant.get("variant_id") for variant in self.variants]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        product_id_set = set(product_ids)
        self.assertTrue(
            all(variant.get("product_id") in product_id_set for variant in self.variants)
        )


if __name__ == "__main__":
    unittest.main()
