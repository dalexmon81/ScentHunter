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
        self.assertEqual(len(self.products), 139)

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


    def test_five_more_fragrances_have_verified_official_detail_pages_and_variants(self):
        expected = {
            "Detour Noir Exclusif": (
                "https://shop.alharamainperfumes.com/eu/haramain-detour-noir-exclusif-100ml-eau-de-parfum.html",
                "Eau de Parfum", 100,
            ),
            "Detour Noir Intense": (
                "https://shop.alharamainperfumes.com/eu/haramain-detour-noir-intense-100ml-eau-de-parfum.html",
                "Eau de Parfum", 100,
            ),
            "Amber Oud Tobacco Edition": (
                "https://shop.alharamainperfumes.com/eu/haramain-amber-oud-200ml-spray-tobacco-edition.html",
                "Eau de Parfum", 200,
            ),
            "Amber Oud Gold Edition": (
                "https://shop.alharamainperfumes.com/eu/amber-oud-gold-edition-120-ml.html",
                "Eau de Parfum", 120,
            ),
            "Amber Oud Dubai Night": (
                "https://shop.alharamainperfumes.com/eu/haramain-amber-oud-gold-dubai-night-75ml-extrait-de-parfum.html",
                "Extrait de Parfum", 75,
            ),
        }
        for name, (source, concentration, size_ml) in expected.items():
            with self.subTest(product=name):
                product = self.products_by_name[name]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), source)
                self.assertEqual(product.get("concentration"), concentration)
                self.assertIn(size_ml, product.get("formats_ml", []))
                matches = [
                    variant for variant in self.variants_for(product)
                    if variant.get("size_ml") == size_ml
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].get("concentration"), concentration)
                self.assertEqual(matches[0].get("source_evidence_url"), source)



    def test_twenty_new_launches_have_official_product_pages_and_supported_sizes(self):
        expected = {
            "Haramain Ayaat Malika Gold": ("https://us.alharamainperfumes.com/en/haramain-ayaat-malika-gold-100ml-extrait-de-parfum.html", None, 100),
            "Haramain Sameera": ("https://us.alharamainperfumes.com/en/haramain-sameera-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Haramain Sameera Noir": ("https://us.alharamainperfumes.com/en/haramain-sameera-noir-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Haramain Empire Aromatique Ombre": ("https://us.alharamainperfumes.com/en/haramain-empire-aromatique-ombre-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Haramain Conception": ("https://us.alharamainperfumes.com/en/haramain-conception-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
            "Haramain Oud Nomad": ("https://us.alharamainperfumes.com/en/haramain-oud-nomad-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
            "Haramain Olaf": ("https://us.alharamainperfumes.com/en/haramain-olaf-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
            "Haramain Harmony": ("https://us.alharamainperfumes.com/en/haramain-harmony-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
            "Haramain Freya": ("https://us.alharamainperfumes.com/en/haramain-freya-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
            "Haramain Amber Oud Imagine Dubai": ("https://us.alharamainperfumes.com/en/haramain-amber-oud-imagine-duabi-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Haramain Amber Oud Future Dubai": ("https://us.alharamainperfumes.com/en/haramain-amber-oud-future-duabi-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Haramain CUPUACU": ("https://us.alharamainperfumes.com/en/haramain-cupuacu-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
            "Haramain L'Aventure Extreme": ("https://us.alharamainperfumes.com/en/haramain-l-aventure-extreme-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Azure Mythique": ("https://us.alharamainperfumes.com/en/azure-mythique-eau-de-parfum-100ml.html", "Eau de Parfum", 100),
            "Haramain Oud Escape": ("https://us.alharamainperfumes.com/en/haramain-oud-escape.html", None, None),
            "Haramain Summer": ("https://us.alharamainperfumes.com/en/haramain-summer.html", "Eau de Parfum", None),
            "Haramain Adventure": ("https://us.alharamainperfumes.com/en/haramain-adventure.html", None, None),
            "Haramain Avalon": ("https://us.alharamainperfumes.com/en/avalon-eau-de-parfum-100ml.html", "Eau de Parfum", 100),
            "Haramain Taj Malaki Velvet": ("https://us.alharamainperfumes.com/en/haramain-taj-malaki-velvet-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
            "Haramain Taj Malaki Noir": ("https://us.alharamainperfumes.com/en/haramain-taj-malaki-noir-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
        }
        for name, (source, concentration, size) in expected.items():
            with self.subTest(product=name):
                product = self.products_by_name[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], source)
                self.assertEqual(product["source_evidence_url"], source)
                if concentration:
                    self.assertEqual(product.get("concentration"), concentration)
                if size:
                    self.assertIn(size, product.get("formats_ml", []))
                    matches = [
                        v for v in self.variants_for(product)
                        if v.get("size_ml") == size
                    ]
                    self.assertEqual(len(matches), 1)
                    self.assertEqual(matches[0].get("source_url"), source)
                    self.assertEqual(matches[0].get("source_evidence_url"), source)
                    if concentration:
                        self.assertEqual(matches[0].get("concentration"), concentration)
                else:
                    self.assertNotIn("formats_ml", product)


    def test_thirteen_additional_al_haramain_pages_and_variants_are_verified(self):
        expected = {
            "Haramain Gold Crystal Sapphire": ("https://us.alharamainperfumes.com/en/haramain-gold-crystal-sapphire-spray-100ml.html", "Extrait de Parfum", 100),
            "L'Aventure Fraiche": ("https://us.alharamainperfumes.com/en/haramain-l-aventure-fraiche-spray.html", "Extrait de Parfum", 100),
            "Haramain Emotion Irisee": ("https://us.alharamainperfumes.com/en/haramain-emotion-irisee-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Haramain CACAU": ("https://us.alharamainperfumes.com/en/haramain-cacau-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
            "Haramain CAJU": ("https://us.alharamainperfumes.com/en/haramain-caju-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
            "Haramain Habibi Dubai Desert": ("https://us.alharamainperfumes.com/en/haramain-habibi-duabi-desert-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Haramain Habibi Dubai Night": ("https://us.alharamainperfumes.com/en/haramain-habibi-duabi-night-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Artisan De Haramain Noir": ("https://us.alharamainperfumes.com/en/artisan-de-haramain-noir-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Artisan De Haramain": ("https://us.alharamainperfumes.com/en/artisan-de-haramain-100ml-extrait-de-parfum.html", None, 100),
            "Haramain Empire Aromatique Lumen": ("https://us.alharamainperfumes.com/en/haramain-empire-aromatique-lumen-100ml-extrait-de-parfum.html", None, 100),
            "Haramain Ayaat Malika": ("https://us.alharamainperfumes.com/en/haramain-ayaat-malika-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Haramain Green Dubai": ("https://us.alharamainperfumes.com/en/haramain-green-dubai-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Haramain Miracle Dubai": ("https://us.alharamainperfumes.com/en/haramain-miracle-dubai-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
        }
        for name, (source, concentration, size) in expected.items():
            with self.subTest(product=name):
                product = self.products_by_name[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], source)
                self.assertEqual(product["source_evidence_url"], source)
                self.assertIn(size, product.get("formats_ml", []))
                if concentration:
                    self.assertEqual(product.get("concentration"), concentration)
                matches = [v for v in self.variants_for(product) if v.get("size_ml") == size]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].get("source_url"), source)
                self.assertEqual(matches[0].get("source_evidence_url"), source)
                if concentration:
                    self.assertEqual(matches[0].get("concentration"), concentration)


if __name__ == "__main__":
    unittest.main()
