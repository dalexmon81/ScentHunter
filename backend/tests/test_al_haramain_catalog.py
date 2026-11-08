"""Regression tests for Al Haramain official EU catalog reconciliation."""
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

    def test_catalog_and_registry_have_exact_name_parity(self):
        catalog_names = {p["canonical_name"].casefold() for p in self.products}
        registry_names = {p["canonical_name"].casefold() for p in self.family["products"]}
        self.assertEqual(catalog_names, registry_names)
        self.assertEqual(len(self.products), 37)

    def test_all_products_use_canonical_family_id(self):
        self.assertTrue(all(p.get("family_id") == "al_haramain_catalog" for p in self.products))

    def test_official_source_is_used_for_verified_names(self):
        verified = [p for p in self.products if p.get("identity_status") == "source_verified_name"]
        self.assertGreaterEqual(len(verified), 25)
        self.assertTrue(all(p.get("source_evidence_url") == "https://shop.alharamainperfumes.com/eu/collection.html" for p in verified))

    def test_confirmed_amber_oud_variants_are_preserved(self):
        ruby = next(p for p in self.products if p["canonical_name"] == "Amber Oud Ruby Edition")
        variants = [v for v in CATALOG["variants"] if v["product_id"] == ruby["product_id"]]
        self.assertEqual({v["size_ml"] for v in variants}, {60, 120, 200})
        self.assertTrue(all(v["concentration"] == "Eau de Parfum" for v in variants))

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
