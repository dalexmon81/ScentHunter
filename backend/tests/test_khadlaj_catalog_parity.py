"""Regression tests for Khadlaj catalog/family registry parity."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


class KhadlajCatalogParityTests(unittest.TestCase):
    def setUp(self):
        self.products = [p for p in CATALOG["products"] if p.get("brand") == "Khadlaj"]
        self.families = [f for f in REGISTRY["families"] if f.get("brand") == "Khadlaj"]

    def test_every_catalog_family_has_a_registry_family(self):
        catalog_family_ids = {p["family_id"] for p in self.products}
        registry_family_ids = {f["family_id"] for f in self.families}
        self.assertEqual(catalog_family_ids, registry_family_ids)

    def test_exact_product_parity_for_each_family(self):
        for family in self.families:
            catalog_names = {
                p["canonical_name"].casefold()
                for p in self.products
                if p["family_id"] == family["family_id"]
            }
            registry_names = {p["canonical_name"].casefold() for p in family["products"]}
            self.assertEqual(catalog_names, registry_names, family["family_id"])

    def test_catalog_product_and_family_names_are_unique(self):
        ids = [p["product_id"] for p in self.products]
        names = [p["canonical_name"].casefold() for p in self.products]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(names), len(set(names)))

    def test_shiyaaka_remains_a_distinct_line(self):
        shiyaaka = next(f for f in self.families if f["family_id"] == "khadlaj_shiyaaka")
        self.assertEqual(len(shiyaaka["products"]), 8)
        self.assertIn("Shiyaaka Blue", {p["canonical_name"] for p in shiyaaka["products"]})

    def test_official_spray_collection_remains_separate(self):
        sprays = next(
            f for f in self.families
            if f["family_id"] == "khadlaj_official_perfume_sprays_2026_11"
        )
        self.assertEqual(len(sprays["products"]), 69)

    def test_perfume_oil_identity_is_not_recast_as_a_spray_variant(self):
        maya = next(p for p in self.products if p["canonical_name"] == "Maya")
        self.assertEqual(maya.get("collection_name"), "Concentrated Perfume Oils")
        self.assertEqual(maya.get("formats_ml"), [20])


if __name__ == "__main__":
    unittest.main()
