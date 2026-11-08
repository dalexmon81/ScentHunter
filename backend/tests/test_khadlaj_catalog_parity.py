"""Regression tests for Khadlaj catalog/family registry coverage."""
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
        self.assertTrue(catalog_family_ids.issubset(registry_family_ids))

    def test_every_catalog_product_is_covered_by_its_family(self):
        for product in self.products:
            family = next(f for f in self.families if f["family_id"] == product["family_id"])
            names = {p["canonical_name"].casefold() for p in family["products"]}
            self.assertIn(product["canonical_name"].casefold(), names, product["canonical_name"])

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
        catalog_family_ids = {p["family_id"] for p in self.products}
        self.assertNotIn(sprays["family_id"], catalog_family_ids)
        self.assertGreater(len(sprays["products"]), 0)

    def test_perfume_oil_identity_is_not_recast_as_a_spray_variant(self):
        maya = next(p for p in next(f for f in self.families if f["family_id"] == "khadlaj_catalog")["products"] if p["canonical_name"] == "Maya")
        self.assertEqual(maya.get("formats_ml"), [20])
        self.assertFalse(any(p["canonical_name"] == "Maya" for p in self.products))


if __name__ == "__main__":
    unittest.main()
