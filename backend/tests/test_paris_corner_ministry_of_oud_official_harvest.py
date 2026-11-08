"""Regression coverage for official Paris Corner Ministry of Oud product records."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Ministry of Oud - Amber Oud": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-amber-oud", "Eau de Parfum"),
    "Ministry of Oud - Gladiators Oath": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-gladiators-oath", None),
    "Ministry of Oud - Maestro's Symphony": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-maestro-s-symphony", None),
    "Ministry of Oud - Nile Whispers": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-nile-whispers", None),
    "Ministry of Oud - Oud Beyond the Wall": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-beyond-the-wall", None),
    "Ministry of Oud - Oud Indonesian": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-indonesian", "Eau de Parfum"),
    "Ministry of Oud - Oud Royal": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-royal", "Eau de Parfum"),
    "Ministry of Oud - Oud Satin": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-satin", None),
    "Ministry of Oud - Romance Reverie": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-romance-reverie", None),
    "Ministry of Oud - Strictly Oud": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-strictly-oud", "Eau de Parfum"),
    "Ministry of Oud Greatest": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-greatest", "Eau de Parfum"),
}


class ParisCornerMinistryOfOudOfficialHarvestTests(unittest.TestCase):
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

    def test_all_ministry_of_oud_records_have_official_detail_pages(self):
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

    def test_each_record_has_one_matching_100ml_variant(self):
        for name, (_url, concentration) in EXPECTED.items():
            with self.subTest(product=name):
                product = self.products[name]
                matches = [
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                    and v.get("size_ml") == 100
                ]
                self.assertEqual(len(matches), 1)
                if concentration is None:
                    self.assertNotIn("concentration", matches[0])
                else:
                    self.assertEqual(matches[0]["concentration"], concentration)

    def test_family_registry_formats_are_aligned(self):
        for name in EXPECTED:
            with self.subTest(product=name):
                family_product = next(
                    p for p in self.family["products"]
                    if p["canonical_name"] == name
                )
                self.assertIn(100, family_product.get("formats_ml", []))

    def test_variant_ids_are_unique_and_all_parents_exist(self):
        ids = [v["variant_id"] for v in self.variants]
        product_ids = {p["product_id"] for p in CATALOG["products"]}
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(v["product_id"] in product_ids for v in self.variants))


if __name__ == "__main__":
    unittest.main()
