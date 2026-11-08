"""Regression tests for Al Haramain listing-level catalog coverage."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


class AlHaramainCatalogTests(unittest.TestCase):
    def setUp(self):
        self.products = [p for p in CATALOG["products"] if p.get("brand") in {"Al Haramain", "Al-Haramain", "Haramain"}]
        self.family = next(f for f in REGISTRY["families"] if f["family_id"] == "al_haramain_catalog")

    def test_catalog_identities_are_covered_by_the_registry(self):
        catalog_names = {p["canonical_name"].casefold() for p in self.products}
        registry_names = {p["canonical_name"].casefold() for p in self.family["products"]}
        self.assertTrue(catalog_names.issubset(registry_names))
        self.assertEqual(len(self.products), 61)

    def test_all_products_use_canonical_family_id(self):
        self.assertTrue(all(p.get("family_id") == "al_haramain_catalog" for p in self.products))

    def test_collection_listings_are_not_misrepresented_as_detail_verified(self):
        self.assertTrue(all(p.get("identity_status") == "source_listed_name" for p in self.products))
        self.assertTrue(all("shop.alharamainperfumes.com" in p.get("source_url", "") for p in self.products))

    def test_unverified_amber_oud_sizes_are_not_invented(self):
        ruby = next(p for p in self.products if p["canonical_name"] == "Amber Oud Ruby Edition")
        variants = [v for v in CATALOG["variants"] if v["product_id"] == ruby["product_id"]]
        self.assertEqual(variants, [])

    def test_oil_and_gift_set_listings_are_not_added_as_spray_variants(self):
        names = {p["canonical_name"] for p in self.products}
        self.assertNotIn("Musk 12ml", names)
        self.assertNotIn("Amber Oud Travelset", names)

    def test_product_and_variant_ids_are_unique(self):
        ids = [p["product_id"] for p in self.products]
        variant_ids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))


if __name__ == "__main__":
    unittest.main()
