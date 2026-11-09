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
        self.assertEqual(len(self.products), 119)

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


    def test_haramain_camellia_official_detail_page_and_100ml_extrait_variant(self):
        product = self.products_by_name["Haramain Camellia"]
        source = "https://us.alharamainperfumes.com/en/haramain-camellia-extrait-de-parfum.html"
        self.assertEqual(product["identity_status"], "source_verified_name")
        self.assertEqual(product["source_url"], source)
        self.assertEqual(product["concentration"], "Extrait de Parfum")
        self.assertEqual(product["formats_ml"], [100])
        matches = self.variants_for(product)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["size_ml"], 100)
        self.assertEqual(matches[0]["concentration"], "Extrait de Parfum")
        self.assertEqual(matches[0]["source_evidence_url"], source)
        registry_names = {p["canonical_name"] for p in self.family["products"]}
        self.assertIn("Haramain Camellia", registry_names)



    def test_five_more_al_haramain_official_detail_pages_and_100ml_variants(self):
        expected = {
            "Haramain Loulou Rose": (
                "https://us.alharamainperfumes.com/en/haramain-loulou-rose-100ml-eau-de-parfum.html",
                "Eau de Parfum",
            ),
            "Haramain Palm Dubai": (
                "https://us.alharamainperfumes.com/en/haramain-palm-dubai-100ml-extrait-de-parfum.html",
                "Extrait de Parfum",
            ),
            "Haramain Gold Crystal Oudh": (
                "https://us.alharamainperfumes.com/en/haramain-gold-crystal-oudh-spray-100ml.html",
                "Extrait de Parfum",
            ),
            "Haramain Black Musk": (
                "https://us.alharamainperfumes.com/en/haramain-black-musk-100ml-spray.html",
                "Eau de Parfum",
            ),
            "Haramain Maryam": (
                "https://us.alharamainperfumes.com/en/maryam-spray.html",
                "Eau de Parfum",
            ),
        }
        for name, (source, concentration) in expected.items():
            with self.subTest(product=name):
                product = self.products_by_name[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], source)
                self.assertEqual(product["concentration"], concentration)
                self.assertEqual(product["formats_ml"], [100])
                matches = self.variants_for(product)
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]["size_ml"], 100)
                self.assertEqual(matches[0]["concentration"], concentration)
                self.assertEqual(matches[0]["source_evidence_url"], source)


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


    def test_twelve_additional_official_launches_have_verified_100ml_variants(self):
        expected = {
            "Amber Oud Smell Dubai": ("https://shop.alharamainperfumes.com/uae/haramain-amber-oud-smell-dubai-100ml-extrait-de-parfum.html", "Extrait de Parfum"),
            "Empire Aromatique Ombre": ("https://shop.alharamainperfumes.com/uae/haramain-empire-aromatique-ombre-100ml-extrait-de-parfum.html", "Extrait de Parfum"),
            "Haramain Olaf": ("https://shop.alharamainperfumes.com/uae/haramain-olaf-100ml-eau-de-parfum.html", "Eau de Parfum"),
            "Haramain Leif": ("https://shop.alharamainperfumes.com/uae/haramain-leif-100ml-eau-de-parfum.html", "Eau de Parfum"),
            "Amber Oud Imagine Dubai": ("https://shop.alharamainperfumes.com/eu/haramain-amber-oud-imagine-duabi-100ml-extrait-de-parfum.html", "Extrait de Parfum"),
            "Amber Oud Gold Lux": ("https://shop.alharamainperfumes.com/default/haramain-amber-oud-gold-lux-100ml-extrait-de-parfum.html", "Extrait de Parfum"),
            "Haramain Sameera": ("https://shop.alharamainperfumes.com/eu/haramain-sameera-100ml-extrait-de-parfum.html", "Extrait de Parfum"),
            "Haramain Sameera Noir": ("https://shop.alharamainperfumes.com/qatar/haramain-sameera-noir-100ml-extrait-de-parfum.html", "Extrait de Parfum"),
            "Haramain Freya": ("https://shop.alharamainperfumes.com/eu/haramain-freya-100ml-eau-de-parfum.html", "Eau de Parfum"),
            "Haramain Harmony": ("https://shop.alharamainperfumes.com/eu/haramain-harmony-100ml-eau-de-parfum.html", "Eau de Parfum"),
            "Haramain CACAU": ("https://shop.alharamainperfumes.com/eu/haramain-cacau-100ml-eau-de-parfum.html", "Eau de Parfum"),
            "Haramain CAJU": ("https://shop.alharamainperfumes.com/eu/haramain-caju-100ml-eau-de-parfum.html", "Eau de Parfum"),
        }
        registry_names = {p["canonical_name"] for p in self.family["products"]}
        for name, (source, concentration) in expected.items():
            with self.subTest(product=name):
                product = self.products_by_name[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], source)
                self.assertEqual(product["concentration"], concentration)
                self.assertEqual(product["formats_ml"], [100])
                matches = self.variants_for(product)
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]["size_ml"], 100)
                self.assertEqual(matches[0]["concentration"], concentration)
                self.assertEqual(matches[0]["source_evidence_url"], source)
                self.assertIn(name, registry_names)

    def test_conflicting_or_mismatched_official_candidates_are_not_promoted(self):
        names = {p["canonical_name"] for p in self.products}
        # Official product-page title and specification disagree on concentration.
        self.assertNotIn("Haramain Adventure", names)
        self.assertNotIn("Haramain Ayaat Malika Gold", names)
        self.assertNotIn("Amber Oud Future Dubai", names)
        # The indexed Gold Mine detail result resolves to a URL slugged as "sport";
        # hold it until the canonical official product URL is corroborated.
        self.assertNotIn("Amber Oud Gold Mine", names)


if __name__ == "__main__":
    unittest.main()
