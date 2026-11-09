"""Regression tests for French Avenue listing-level identity evidence."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Safari Breeze": "https://www.fragrantica.com/designers/French-Avenue.html",
}


class FrenchAvenueCatalogTests(unittest.TestCase):
    def test_listed_fragrance_identities_keep_their_actual_source_level(self):
        products = {
            p["canonical_name"]: p for p in CATALOG["products"]
            if p.get("brand") == "French Avenue"
        }
        for name, url in EXPECTED.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                self.assertEqual(products[name]["source_url"], url)
                self.assertEqual(products[name]["identity_status"], "source_listed_name")

    def test_family_registry_covers_new_catalog_identities(self):
        family = next(
            f for f in REGISTRY["families"]
            if f["family_id"] == "french_avenue_catalog"
        )
        names = {p["canonical_name"] for p in family["products"]}
        self.assertTrue(set(EXPECTED).issubset(names))

    def test_product_ids_and_brand_name_pairs_are_unique(self):
        products = CATALOG["products"]
        ids = [p["product_id"] for p in products]
        pairs = [
            (p.get("brand") or p.get("brand_name"), p.get("canonical_name") or p.get("name"))
            for p in products
        ]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_no_commercial_offer_fields_were_added(self):
        for product in CATALOG["products"]:
            if product.get("brand") == "French Avenue" and product.get("canonical_name") in EXPECTED:
                for field in ("price", "stock", "availability", "shipping_cost", "store_url", "gtin"):
                    self.assertNotIn(field, product)


    def test_verified_official_product_pages_have_explicit_variants(self):
        expected = {
            "Liquid Brun": ("https://frenchavenue.com/products/liquid-brun", "Eau de Parfum", 100),
            "Liquid Brun Limited Edition": ("https://frenchavenue.com/products/liquid-brun-limited-edition", "Extrait de Parfum", 150),
            "Spectre Ghost": ("https://frenchavenue.com/products/spectre-ghost", "Eau de Parfum", 80),
            "Vulcan Feu": ("https://frenchavenue.com/products/vulcan-feu", "Eau de Parfum", 100),
            "Azzure Aoud": ("https://frenchavenue.com/products/azzure-aoud", "Eau de Parfum", 100),
            "Amber Empire": ("https://frenchavenue.com/products/amber-empire", None, None),
            "Royal Blend Sequoia": ("https://frenchavenue.com/products/royal-blend-sequoia", "Extrait de Parfum", 100),
            "Noble Cedar": ("https://frenchavenue.com/products/noble-cedar", "Eau de Parfum", 100),
            "Jasmere": ("https://frenchavenue.com/products/jasmere", "Eau de Parfum", 100),
            "Atlantis Extrait": ("https://frenchavenue.com/products/atlantis-extrait", "Extrait de Parfum", 100),
            "Ambroise Pour Femme": ("https://frenchavenue.com/products/ambroise-pour-femme", "Eau de Parfum", 100),
            "Aether": ("https://frenchavenue.com/products/aether", "Extrait de Parfum", 100),
            "Royal Blend": ("https://frenchavenue.com/products/royal-blend", "Eau de Parfum", 100),
            "Imperial Ocean": ("https://frenchavenue.com/products/imperial-ocean", "Eau de Parfum", 100),
            "Cocoa Morado": ("https://frenchavenue.com/products/cocoa-morado", "Eau de Parfum", 100),
            "Spectre Wraith": ("https://frenchavenue.com/products/spectre-wraith", "Eau de Parfum", 80),
            "Eclair Affair": ("https://frenchavenue.com/products/eclair-affair", "Extrait de Parfum", 100),
            "Royal Blend Nero": ("https://frenchavenue.com/products/royal-blend-nero", "Extrait de Parfum", 100),
            "Papa Yeah": ("https://frenchavenue.com/products/papa-yeah", "Eau de Parfum", 100),
            "Spirito Mystic": ("https://frenchavenue.com/products/spirito-mystic", "Extrait de Parfum", 100),
        }
        products = {
            p["canonical_name"]: p for p in CATALOG["products"]
            if p.get("brand") == "French Avenue"
        }
        variants = CATALOG.get("variants", [])
        for name, (source, concentration, size) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                product = products[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], source)
                if concentration:
                    self.assertEqual(product.get("concentration"), concentration)
                if size:
                    self.assertIn(size, product.get("formats_ml", []))
                    matches = [
                        v for v in variants
                        if v.get("product_id") == product["product_id"]
                        and v.get("size_ml") == size
                    ]
                    self.assertEqual(len(matches), 1)
                    self.assertEqual(matches[0].get("source_url"), source)
                    self.assertEqual(matches[0].get("source_evidence_url"), source)

    def test_dusk_till_dawn_bundle_is_not_a_canonical_fragrance(self):
        self.assertNotIn(
            "Dusk Till Dawn",
            {p.get("canonical_name") for p in CATALOG["products"] if p.get("brand") == "French Avenue"},
        )


if __name__ == "__main__":
    unittest.main()
