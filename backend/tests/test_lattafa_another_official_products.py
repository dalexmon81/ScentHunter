"""Regression tests for twelve more Lattafa official detail pages."""

import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG_PATH = BACKEND / "product_catalog.json"
FAMILY_PATH = BACKEND / "family_registry.json"
PRODUCTS = {
    "Khamrah Mira": ("https://lattafa.com/product/khamrah-mira/", 100),
    "Matcha Swirl – Give Me Gourmand": ("https://lattafa.com/product/matcha-swirl-give-me-gourmand/", 75),
    "Reem": ("https://lattafa.com/product/reem/", 100),
    "Lahdath": ("https://lattafa.com/product/lahdath/", 80),
    "Art Of Wood": ("https://lattafa.com/product/art-of-wood/", 100),
    "Ansaam Gold": ("https://lattafa.com/product/ansaam-gold/", 100),
    "Petra": ("https://lattafa.com/product/petra/", 100),
    "Natural Oud": ("https://lattafa.com/product/natural-oud/", None),
    "Sur Mesure Noir": ("https://lattafa.com/product/sur-mesure-noir/", 100),
    "Brioche Vanille": ("https://lattafa.com/product/brioche-vanille/", 100),
    "Taraf": ("https://lattafa.com/product/taraf/", 100),
    "Art of Nature II": ("https://lattafa.com/product/art-of-nature-ii/", None),
}


class LattafaAnotherOfficialProductsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        with FAMILY_PATH.open(encoding="utf-8") as handle:
            registry = json.load(handle)
        cls.products = cls.catalog["products"]
        cls.variants = cls.catalog["variants"]
        cls.family = next(f for f in registry["families"] if f["family_id"] == "lattafa_catalog")

    def test_official_products_and_family_entries_are_unique(self):
        for name, (url, _) in PRODUCTS.items():
            with self.subTest(product=name):
                matches = [p for p in self.products if p.get("brand_name") == "Lattafa" and p.get("canonical_name") == name]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].get("identity_status"), "source_verified_name")
                self.assertEqual(matches[0].get("source_url"), url)
                self.assertEqual(len([p for p in self.family["products"] if p.get("canonical_name") == name]), 1)

    def test_only_explicit_sizes_create_variants(self):
        for name, (_, size) in PRODUCTS.items():
            with self.subTest(product=name):
                product = next(p for p in self.products if p.get("brand_name") == "Lattafa" and p.get("canonical_name") == name)
                variants = [v for v in self.variants if v.get("product_id") == product["product_id"]]
                if size is None:
                    self.assertEqual(variants, [])
                    self.assertNotIn("formats_ml", product)
                else:
                    self.assertEqual(len(variants), 1)
                    self.assertEqual(variants[0].get("size_ml"), size)
                    self.assertEqual(product.get("formats_ml"), [size])

    def test_ids_are_unique_and_variants_have_canonical_parents(self):
        product_ids = [p.get("product_id") for p in self.products]
        variant_ids = [v.get("variant_id") for v in self.variants]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertTrue(all(v.get("product_id") in set(product_ids) for v in self.variants))


if __name__ == "__main__":
    unittest.main()
