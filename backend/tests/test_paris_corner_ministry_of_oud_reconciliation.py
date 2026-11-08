"""Regression coverage for official Paris Corner Ministry of Oud products."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Ministry of Oud - Amber Oud": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-amber-oud", True),
    "Ministry of Oud - Oud Indonesian": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-indonesian", True),
    "Ministry of Oud - Oud Royal": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-royal", True),
    "Ministry of Oud - Oud Satin": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-satin", False),
    "Ministry of Oud - Strictly Oud": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-strictly-oud", True),
    "Ministry of Oud Greatest": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-greatest", True),
    "Ministry of Oud - Gladiators Oath": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-gladiators-oath", False),
    "Ministry of Oud - Maestro's Symphony": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-maestro-s-symphony", False),
    "Ministry of Oud - Nile Whispers": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-nile-whispers", False),
    "Ministry of Oud - Oud Beyond the Wall": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-beyond-the-wall", False),
    "Ministry of Oud - Romance Reverie": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-romance-reverie", False),
}


class ParisCornerMinistryOfOudReconciliationTests(unittest.TestCase):
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

    def test_all_official_ministry_of_oud_products_have_canonical_records(self):
        for name, (url, has_edp_evidence) in EXPECTED.items():
            with self.subTest(product=name):
                product = self.products[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertEqual(product["collection_name"], "Ministry of Oud")
                self.assertEqual(product["formats_ml"], [100])
                if has_edp_evidence:
                    self.assertEqual(product["concentration"], "Eau de Parfum")
                else:
                    self.assertNotIn("concentration", product)

    def test_each_product_has_one_matching_100ml_variant(self):
        for name, (url, has_edp_evidence) in EXPECTED.items():
            product = self.products[name]
            matches = [
                v for v in self.variants
                if v.get("product_id") == product["product_id"]
                and v.get("size_ml") == 100
            ]
            self.assertEqual(len(matches), 1, name)
            self.assertEqual(matches[0]["source_url"], url)
            if has_edp_evidence:
                self.assertEqual(matches[0]["concentration"], "Eau de Parfum")
            else:
                self.assertNotIn("concentration", matches[0])

    def test_family_registry_formats_are_aligned(self):
        for name in EXPECTED:
            with self.subTest(product=name):
                row = next(p for p in self.family["products"] if p["canonical_name"] == name)
                self.assertIn(100, row.get("formats_ml", []))

    def test_ids_and_parent_references_are_unique_and_valid(self):
        product_ids = [p["product_id"] for p in CATALOG["products"]]
        variant_ids = [v["variant_id"] for v in self.variants]
        known_products = set(product_ids)
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertTrue(all(v["product_id"] in known_products for v in self.variants))


if __name__ == "__main__":
    unittest.main()
