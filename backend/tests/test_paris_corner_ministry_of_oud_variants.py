"""Regression coverage for Ministry of Oud products on the official Paris Corner store."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Ministry of Oud - Amber Oud": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-amber-oud", "Eau de Parfum"),
    "Ministry of Oud - Oud Indonesian": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-indonesian", "Eau de Parfum"),
    "Ministry of Oud - Oud Royal": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-royal", "Eau de Parfum"),
    "Ministry of Oud - Oud Satin": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-satin", None),
    "Ministry of Oud - Strictly Oud": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-strictly-oud", "Eau de Parfum"),
    "Ministry of Oud Greatest": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-greatest", "Eau de Parfum"),
    "Ministry of Oud - Gladiators Oath": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-gladiators-oath", None),
    "Ministry of Oud - Maestro's Symphony": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-maestro-s-symphony", None),
    "Ministry of Oud - Nile Whispers": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-nile-whispers", None),
    "Ministry of Oud - Oud Beyond the Wall": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-beyond-the-wall", None),
    "Ministry of Oud - Romance Reverie": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-romance-reverie", None),
}


class ParisCornerMinistryOfOudOfficialVariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = {
            p["canonical_name"]: p
            for p in CATALOG["products"]
            if p.get("brand_name") == "Paris Corner"
        }
        cls.variants = CATALOG["variants"]
        cls.family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "paris_corner_catalog"
        )

    def test_official_pages_and_100ml_variants(self):
        for name, (url, concentration) in EXPECTED.items():
            with self.subTest(product=name):
                product = self.products[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertEqual(product["formats_ml"], [100])
                if concentration is None:
                    self.assertNotIn("concentration", product)
                else:
                    self.assertEqual(product["concentration"], concentration)
                matches = [
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                    and v.get("size_ml") == 100
                    and v.get("concentration") == concentration
                ]
                self.assertEqual(len(matches), 1)

    def test_family_registry_formats_are_aligned(self):
        for name in EXPECTED:
            with self.subTest(product=name):
                registry_product = next(
                    p for p in self.family["products"]
                    if p["canonical_name"] == name
                )
                self.assertIn(100, registry_product.get("formats_ml", []))

    def test_variant_ids_are_unique_and_parent_products_exist(self):
        ids = [v["variant_id"] for v in self.variants]
        product_ids = {p["product_id"] for p in CATALOG["products"]}
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(v["product_id"] in product_ids for v in self.variants))


if __name__ == "__main__":
    unittest.main()
