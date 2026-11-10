"""Regression tests for Gulf Orchid official new-arrival product identities."""

import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
EXPECTED = {
    "Maze": "https://shop-gulforchid.com/products/maze",
    "Mosaic": "https://shop-gulforchid.com/products/mosaic",
    "Rice Milk": "https://shop-gulforchid.com/products/rice-milk",
    "Royal Rose": "https://shop-gulforchid.com/products/royal-rose",
}


class GulfOrchidNewArrivalsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = {
            row.get("canonical_name"): row
            for row in cls.catalog.get("products", [])
            if row.get("brand_name") == "Gulf Orchid"
        }

    def test_official_new_arrivals_are_unique_and_source_verified(self):
        for name, url in EXPECTED.items():
            with self.subTest(name=name):
                self.assertIn(name, self.products)
                row = self.products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), url)
                self.assertEqual(row.get("source_product_url"), url)
                self.assertEqual(row.get("source_evidence_url"), url)
                self.assertEqual(row.get("concentration"), "Eau de Parfum")
                self.assertEqual(row.get("formats_ml"), [100])
                self.assertEqual(
                    len([
                        product for product in self.catalog["products"]
                        if product.get("brand_name") == "Gulf Orchid"
                        and product.get("canonical_name") == name
                    ]),
                    1,
                )

    def test_each_new_arrival_has_one_provenanced_100ml_edp_variant(self):
        variants = self.catalog.get("variants", [])
        for name, url in EXPECTED.items():
            with self.subTest(name=name):
                row = self.products[name]
                matching = [
                    variant for variant in variants
                    if variant.get("product_id") == row["product_id"]
                    and variant.get("size_ml") == 100
                ]
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0].get("concentration"), "Eau de Parfum")
                self.assertEqual(matching[0].get("source_evidence_url"), url)

    def test_new_arrivals_are_present_in_family_registry(self):
        registry_path = Path(__file__).resolve().parents[1] / "family_registry.json"
        with registry_path.open(encoding="utf-8") as handle:
            registry = json.load(handle)
        family = next(
            family for family in registry["families"]
            if family.get("family_id") == "gulf_orchid_catalog"
        )
        registered = {
            product["canonical_name"]: product
            for product in family.get("products", [])
        }
        for name in EXPECTED:
            with self.subTest(name=name):
                self.assertIn(name, registered)
                self.assertEqual(registered[name].get("formats_ml"), [100])


if __name__ == "__main__":
    unittest.main()
