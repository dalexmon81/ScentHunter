"""Regression coverage for nine further Lattafa official detail pages."""

import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
PRODUCTS = {
    "Ramaad Al Oud": ("https://lattafa.com/product/ramaad-al-oud/", 100),
    "Asad Polar": ("https://lattafa.com/product/asad-polar/", 100),
    "Beyond Precious": ("https://lattafa.com/product/beyond-precious/", 100),
    "Harlequin Cream – Give Me Gourmand": ("https://lattafa.com/product/harlequin-cream-give-me-gourmand/", 75),
    "Rave Now- women": ("https://lattafa.com/product/rave-now-women/", 100),
    "Rave Now- White": ("https://lattafa.com/product/rave-now-white/", 100),
    "Rave Now- rouge": ("https://lattafa.com/product/rave-now-rouge/", 100),
    "Fearless": ("https://lattafa.com/product/fearless/", 100),
    "Raw Human": ("https://lattafa.com/product/raw-human/", 100),
}


class LattafaFurtherOfficialProductsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = cls.catalog["products"]
        cls.variants = cls.catalog["variants"]

    def test_official_identities_and_family_registry_entries(self):
        with open(Path(__file__).resolve().parents[1] / "family_registry.json", encoding="utf-8") as handle:
            registry = json.load(handle)
        family = next(f for f in registry["families"] if f["family_id"] == "lattafa_catalog")
        for name, (url, _) in PRODUCTS.items():
            with self.subTest(product=name):
                matches = [p for p in self.products if p.get("brand_name") == "Lattafa" and p.get("canonical_name") == name]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].get("identity_status"), "source_verified_name")
                self.assertEqual(matches[0].get("source_url"), url)
                self.assertEqual(len([p for p in family["products"] if p.get("canonical_name") == name]), 1)

    def test_explicit_sizes_and_no_inferred_concentration(self):
        for name, (url, size) in PRODUCTS.items():
            with self.subTest(product=name):
                product = next(p for p in self.products if p.get("brand_name") == "Lattafa" and p.get("canonical_name") == name)
                variants = [v for v in self.variants if v.get("product_id") == product["product_id"]]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("size_ml"), size)
                self.assertNotIn("concentration", variants[0])
                self.assertEqual(product.get("formats_ml"), [size])

    def test_product_and_variant_ids_are_unique_and_no_orphans(self):
        product_ids = [p.get("product_id") for p in self.products]
        variant_ids = [v.get("variant_id") for v in self.variants]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertTrue(all(v.get("product_id") in set(product_ids) for v in self.variants))


if __name__ == "__main__":
    unittest.main()
