"""Regression tests for Paris Corner canonical catalog and family registry parity."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

class ParisCornerCatalogParityTests(unittest.TestCase):
    def setUp(self):
        self.products = [p for p in CATALOG["products"] if p.get("brand") == "Paris Corner"]
        self.family = next(f for f in REGISTRY["families"] if f["family_id"] == "paris_corner_catalog")

    def test_all_canonical_products_have_registry_entries(self):
        catalog_names = {p["canonical_name"].casefold() for p in self.products}
        registry_names = {p["canonical_name"].casefold() for p in self.family["products"]}
        self.assertEqual(catalog_names, registry_names)
        self.assertEqual(len(self.products), 252)
        self.assertEqual(len(self.family["products"]), 252)

    def test_all_products_use_the_canonical_family_id(self):
        self.assertTrue(all(p.get("family_id") == "paris_corner_catalog" for p in self.products))

    def test_sources_are_official_paris_corner_pages(self):
        self.assertTrue(all((p.get("source_url") or "").startswith("https://www.pariscornerperfumes.com/") for p in self.products))

    def test_brand_collection_label_is_not_a_canonical_fragrance(self):
        self.assertFalse(any(p["canonical_name"].casefold() == "ministry of gourmand" for p in self.products))

    def test_product_ids_and_canonical_names_are_unique(self):
        ids = [p["product_id"] for p in self.products]
        names = [p["canonical_name"].casefold() for p in self.products]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(names), len(set(names)))

if __name__ == "__main__":
    unittest.main()
