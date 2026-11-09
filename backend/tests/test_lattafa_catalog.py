"""Regression tests for official Lattafa identity additions and family assignment."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


class LattafaCatalogTests(unittest.TestCase):
    def test_official_product_page_identities_exist(self):
        products = {
            p["canonical_name"]: p for p in CATALOG["products"]
            if p.get("brand") == "Lattafa"
        }
        for name, url in {
            "Queen of Arabia": "https://lattafa.com/product/queen-of-arabia/",
            "Musamam Black Intense": "https://lattafa.com/product/musamam-black-intense/",
        }.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                self.assertEqual(products[name]["source_url"], url)
                expected_status = "source_verified_name"
                self.assertEqual(products[name]["identity_status"], expected_status)

    def test_lattta_family_registry_contains_both_names(self):
        names = {
            p["canonical_name"]
            for family in REGISTRY["families"]
            if family.get("brand") == "Lattafa"
            for p in family["products"]
        }
        self.assertTrue({"Queen of Arabia", "Musamam Black Intense"}.issubset(names))

    def test_asad_line_contains_only_asad_products(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "lattafa_asad")
        names = {p["canonical_name"] for p in family["products"]}
        self.assertEqual(names, {"Asad", "Asad Zanzibar", "Asad Bourbon", "Asad Elixir"})

    def test_non_asad_lattta_products_are_in_the_general_family(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "lattafa_catalog")
        names = {p["canonical_name"] for p in family["products"]}
        self.assertTrue({"Queen of Arabia", "Musamam White Intense", "Musamam Black Intense"}.issubset(names))

    def test_no_duplicate_ids_or_brand_name_pairs(self):
        products = CATALOG["products"]
        ids = [p["product_id"] for p in products]
        pairs = [(p.get("brand") or p.get("brand_name"), p["canonical_name"]) for p in products]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_no_offer_or_unverified_variant_fields_added(self):
        for p in CATALOG["products"]:
            if p.get("canonical_name") in {"Queen of Arabia", "Musamam Black Intense"} and p.get("brand") == "Lattafa":
                for field in ("price", "stock", "availability", "shipping_cost", "store_url"):
                    self.assertNotIn(field, p)


    def test_new_official_lattta_product_pages_have_explicit_size_variants(self):
        expected = {
            "Atlas Canyon": ("https://lattafa.com/product/atlas-canyon/", 55),
            "Atlas Glacial Valley": ("https://lattafa.com/product/atlas-glacial-valley/", 55),
            "Raghad": ("https://lattafa.com/product/raghad/", 100),
            "Ramaad Al Oud": ("https://lattafa.com/product/ramaad-al-oud/", 100),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand") == "Lattafa"
        }
        variants = CATALOG.get("variants", [])
        family_names = {
            row.get("canonical_name")
            for family in REGISTRY.get("families", [])
            if family.get("family_id") == "lattafa_catalog"
            for row in family.get("products", [])
        }
        for name, (source, size_ml) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                product = products[name]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), source)
                self.assertIn(size_ml, product.get("formats_ml", []))
                self.assertIn(name, family_names)
                matches = [
                    variant for variant in variants
                    if variant.get("product_id") == product.get("product_id")
                    and variant.get("size_ml") == size_ml
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].get("source_evidence_url"), source)


    def test_three_additional_official_lattta_pages_have_100ml_variants(self):
        expected = {
            "Majd Al Sultan Black Intense": (
                "https://lattafa.com/product/majd-al-sultan-black-intense/", "Men"
            ),
            "Badee Al Oud Amethyst Fusion": (
                "https://lattafa.com/product/badee-al-oud-amethyst-fusion/", "Unisex"
            ),
            "Farfasha": (
                "https://lattafa.com/product/farfasha/", "Women"
            ),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand") == "Lattafa"
        }
        variants = CATALOG.get("variants", [])
        family_names = {
            row.get("canonical_name")
            for family in REGISTRY.get("families", [])
            if family.get("family_id") == "lattafa_catalog"
            for row in family.get("products", [])
        }
        for name, (source, gender) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                product = products[name]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), source)
                self.assertEqual(product.get("gender"), gender)
                self.assertIn(100, product.get("formats_ml", []))
                self.assertIn(name, family_names)
                matches = [
                    variant for variant in variants
                    if variant.get("product_id") == product.get("product_id")
                    and variant.get("size_ml") == 100
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].get("source_evidence_url"), source)



    def test_twelve_additional_official_lattta_pages_have_explicit_size_variants(self):
        expected = {
            "Khamrah Mira": ("https://lattafa.com/product/khamrah-mira/", 100, "Women"),
            "London the City of Contrast": ("https://lattafa.com/product/london-the-city-of-contrast/", 100, "Unisex"),
            "Atheeri": ("https://lattafa.com/product/atheeri/", 100, "Women"),
            "Fearless": ("https://lattafa.com/product/fearless/", 100, "Men"),
            "Matcha Swirl – Give Me Gourmand": ("https://lattafa.com/product/matcha-swirl-give-me-gourmand/", 75, "Unisex"),
            "Harlequin Cream – Give Me Gourmand": ("https://lattafa.com/product/harlequin-cream-give-me-gourmand/", 75, "Unisex"),
            "Beyond Precious": ("https://lattafa.com/product/beyond-precious/", 100, "Women"),
            "Creative Art": ("https://lattafa.com/product/creative-art/", 100, None),
            "Queen of Roses": ("https://lattafa.com/product/queen-of-roses/", 100, "Women"),
            "New York the City of Dreams": ("https://lattafa.com/product/new-york-the-city-of-dreams/", 100, "Unisex"),
            "King of Arabia": ("https://lattafa.com/product/king-of-arabia/", 100, "Men"),
            "Love In Paris": ("https://lattafa.com/product/love-in-paris/", 100, "Unisex"),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand") == "Lattafa"
        }
        variants = CATALOG.get("variants", [])
        family_names = {
            row.get("canonical_name")
            for family in REGISTRY.get("families", [])
            if family.get("family_id") == "lattafa_catalog"
            for row in family.get("products", [])
        }
        for name, (source, size, gender) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                product = products[name]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), source)
                self.assertEqual(product.get("source_evidence_url"), source)
                self.assertEqual(product.get("formats_ml"), [size])
                if gender:
                    self.assertEqual(product.get("gender"), gender)
                self.assertIn(name, family_names)
                matches = [
                    variant for variant in variants
                    if variant.get("product_id") == product.get("product_id")
                    and variant.get("size_ml") == size
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].get("source_url"), source)
                self.assertEqual(matches[0].get("source_evidence_url"), source)



if __name__ == "__main__":
    unittest.main()
