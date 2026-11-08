"""Regression tests for 25 additional Lattafa official product pages."""

import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG_PATH = BACKEND / "product_catalog.json"
FAMILY_PATH = BACKEND / "family_registry.json"
PRODUCTS = {
    "Ghinwa": ("https://lattafa.com/product/ghinwa/", [100]),
    "Hayaam": ("https://lattafa.com/product/hayaam/", [100]),
    "Durrah": ("https://lattafa.com/product/durrah/", [100]),
    "Classic Stone": ("https://lattafa.com/product/classic-stone/", [100]),
    "Vintage castle": ("https://lattafa.com/product/vintage-castle/", [100]),
    "Mughal Fort": ("https://lattafa.com/product/mughal-fort/", [100]),
    "Al Dana": ("https://lattafa.com/product/al-dana/", [100]),
    "Remas": ("https://lattafa.com/product/remas/", [100]),
    "Zikra": ("https://lattafa.com/product/zikra/", [100]),
    "Al Jawhara": ("https://lattafa.com/product/al-jawhara/", [100]),
    "Khanjar": ("https://lattafa.com/product/khanjar/", [85]),
    "Thouq": ("https://lattafa.com/product/thouq/", [80]),
    "Gharam": ("https://lattafa.com/product/gharam/", [20, 100]),
    "Affection": ("https://lattafa.com/product/affection/", [20]),
    "Al Khas Winners Trophy Silver": ("https://lattafa.com/product/al-khas-winners-trophy-silver/", [100]),
    "Maharjan Silver": ("https://lattafa.com/product/maharjan-silver/", [100]),
    "Maharjan Gold": ("https://lattafa.com/product/maharjan-gold/", [100]),
    "Al Ameed Silver": ("https://lattafa.com/product/al-ameed-silver/", [100]),
    "Ansaam Silver": ("https://lattafa.com/product/ansaam-silver/", [100]),
    "Khalid": ("https://lattafa.com/product/khalid/", [80]),
    "Al Qiam Silver": ("https://lattafa.com/product/al-qiam-silver/", [100]),
    "Tharwah Silver": ("https://lattafa.com/product/tharwah-silver/", [100]),
    "Toleen": ("https://lattafa.com/product/toleen/", [100]),
    "Lujain": ("https://lattafa.com/product/lujain/", [100]),
    "Al Narjis": ("https://lattafa.com/product/al-narjis/", [100]),
}


class LattafaFurtherNicheOfficialProductsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        with FAMILY_PATH.open(encoding="utf-8") as handle:
            registry = json.load(handle)
        cls.products = cls.catalog["products"]
        cls.variants = cls.catalog["variants"]
        cls.family = next(f for f in registry["families"] if f["family_id"] == "lattafa_catalog")

    def test_official_products_and_family_registry_entries_are_unique(self):
        for name, (url, _) in PRODUCTS.items():
            with self.subTest(product=name):
                matches = [p for p in self.products if p.get("brand_name") == "Lattafa" and p.get("canonical_name") == name]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].get("identity_status"), "source_verified_name")
                self.assertEqual(matches[0].get("source_url"), url)
                self.assertEqual(len([p for p in self.family["products"] if p.get("canonical_name") == name]), 1)

    def test_only_explicit_size_variants_are_recorded(self):
        for name, (_, sizes) in PRODUCTS.items():
            with self.subTest(product=name):
                product = next(p for p in self.products if p.get("brand_name") == "Lattafa" and p.get("canonical_name") == name)
                variants = [v for v in self.variants if v.get("product_id") == product["product_id"]]
                self.assertEqual(sorted(v.get("size_ml") for v in variants), sizes)
                self.assertEqual(product.get("formats_ml"), sizes)
        affection = next(p for p in self.products if p.get("brand_name") == "Lattafa" and p.get("canonical_name") == "Affection")
        affection_variant = next(v for v in self.variants if v.get("product_id") == affection["product_id"])
        self.assertEqual(affection_variant.get("source_url"), "https://lattafa.com/product/affection-20ml/")

    def test_ids_are_unique_and_variants_have_canonical_parents(self):
        product_ids = [p.get("product_id") for p in self.products]
        variant_ids = [v.get("variant_id") for v in self.variants]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertTrue(all(v.get("product_id") in set(product_ids) for v in self.variants))


if __name__ == "__main__":
    unittest.main()
