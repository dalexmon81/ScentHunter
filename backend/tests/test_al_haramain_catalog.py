"""Regression tests for Al Haramain catalog coverage and official detail evidence."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


class AlHaramainCatalogTests(unittest.TestCase):
    def setUp(self):
        self.products = [
            p for p in CATALOG["products"]
            if p.get("brand") in {"Al Haramain", "Al-Haramain", "Haramain"}
        ]
        self.products_by_name = {p["canonical_name"]: p for p in self.products}
        self.variants = CATALOG["variants"]
        self.family = next(
            f for f in REGISTRY["families"]
            if f["family_id"] == "al_haramain_catalog"
        )

    def variants_for(self, product):
        return [v for v in self.variants if v["product_id"] == product["product_id"]]

    def test_catalog_identities_are_covered_by_the_registry(self):
        catalog_names = {p["canonical_name"].casefold() for p in self.products}
        registry_names = {p["canonical_name"].casefold() for p in self.family["products"]}
        self.assertTrue(catalog_names.issubset(registry_names))
        self.assertEqual(len(self.products), 106)

    def test_all_products_use_canonical_family_id(self):
        self.assertTrue(all(p.get("family_id") == "al_haramain_catalog" for p in self.products))

    def test_collection_only_rows_remain_listing_level(self):
        collection_only = [p for p in self.products if p["identity_status"] == "source_listed_name"]
        self.assertTrue(collection_only)
        self.assertTrue(all("shop.alharamainperfumes.com" in p.get("source_url", "") for p in collection_only))

    def test_eight_fragrances_have_official_detail_page_evidence(self):
        expected = {
            "Amber Oud Ruby Edition": ("Eau de Parfum", {100, 120}),
            "Amber Oud Gold Edition Extreme": ("Extrait de Parfum", {100}),
            "Azlan Oud Bleu Edition": ("Extrait de Parfum", {100}),
            "Azlan Oud Saffron Edition": ("Extrait de Parfum", {100}),
            "L'Aventure Grapefruit": ("Extrait de Parfum", {100}),
            "L'Aventure Iris": ("Extrait de Parfum", {100}),
            "L'Aventure Ciel": ("Extrait de Parfum", {100}),
            "Amber Oud Aqua Dubai": ("Extrait de Parfum", {100}),
        }
        for name, (concentration, sizes) in expected.items():
            with self.subTest(product=name):
                product = self.products_by_name[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertIn("/eu/", product["source_url"])
                self.assertIn("/products/", product["source_url"]) if "/products/" in product["source_url"] else self.assertTrue(product["source_url"].endswith(".html"))
                self.assertEqual(product["concentration"], concentration)
                self.assertEqual(
                    {v["size_ml"] for v in self.variants_for(product)},
                    sizes,
                )
                self.assertTrue(sizes.issubset(set(product["formats_ml"])))
                self.assertTrue(all(v.get("concentration") == concentration for v in self.variants_for(product)))

    def test_unverified_amber_oud_sizes_are_not_invented(self):
        gold = self.products_by_name["Amber Oud Gold Edition Extreme"]
        self.assertEqual({v["size_ml"] for v in self.variants_for(gold)}, {100})
        ruby = self.products_by_name["Amber Oud Ruby Edition"]
        self.assertEqual({v["size_ml"] for v in self.variants_for(ruby)}, {100, 120})

    def test_oil_and_gift_set_listings_are_not_added_as_spray_variants(self):
        names = {p["canonical_name"] for p in self.products}
        self.assertNotIn("Musk 12ml", names)
        self.assertNotIn("Amber Oud Travelset", names)
        self.assertNotIn("Gift Set Aqua Dubai", names)

    def test_product_and_variant_ids_are_unique(self):
        ids = [p["product_id"] for p in self.products]
        variant_ids = [v["variant_id"] for v in self.variants]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))


if __name__ == "__main__":
    unittest.main()
