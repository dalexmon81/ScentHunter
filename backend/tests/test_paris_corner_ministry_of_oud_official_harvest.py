"""Regression coverage for Paris Corner Harrier and Ministry of Oud official pages."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Harrier Absoulte": ("https://www.pariscornerperfumes.com/products/harrier-absoulte", True),
    "Ministry of Oud - Amber Oud": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-amber-oud", True),
    "Ministry of Oud - Gladiators Oath": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-gladiators-oath", False),
    "Ministry of Oud - Maestro's Symphony": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-maestro-s-symphony", False),
    "Ministry of Oud - Nile Whispers": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-nile-whispers", False),
    "Ministry of Oud - Oud Beyond the Wall": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-beyond-the-wall", False),
    "Ministry of Oud - Oud Indonesian": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-indonesian", True),
    "Ministry of Oud - Oud Royal": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-royal", True),
    "Ministry of Oud - Oud Satin": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-satin", False),
    "Ministry of Oud - Romance Reverie": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-romance-reverie", False),
    "Ministry of Oud - Strictly Oud": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-strictly-oud", True),
    "Ministry of Oud Greatest": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-greatest", True),
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

    def test_official_detail_pages_and_100ml_variants(self):
        for name, (url, is_edp) in EXPECTED.items():
            with self.subTest(product=name):
                product = self.products[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertEqual(product["formats_ml"], [100])
                matches = [
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                    and v.get("size_ml") == 100
                ]
                self.assertEqual(len(matches), 1)
                if is_edp:
                    self.assertEqual(product["concentration"], "Eau de Parfum")
                    self.assertEqual(matches[0]["concentration"], "Eau de Parfum")
                else:
                    self.assertNotIn("concentration", product)
                    self.assertNotIn("concentration", matches[0])

    def test_family_registry_has_the_verified_size(self):
        for name in EXPECTED:
            with self.subTest(product=name):
                row = next(p for p in self.family["products"] if p["canonical_name"] == name)
                self.assertIn(100, row.get("formats_ml", []))

    def test_attratus_is_an_alias_of_attractus_not_a_second_identity(self):
        product = self.products["Attractus"]
        self.assertIn("Attratus", product["aliases"])
        self.assertIn("Paris Corner Attratus", product["aliases"])
        names = [p["canonical_name"].casefold() for p in self.products.values()]
        self.assertEqual(names.count("attractus"), 1)
        self.assertNotIn("attratus", names)
        registry_names = [p["canonical_name"].casefold() for p in self.family["products"]]
        self.assertEqual(registry_names.count("attractus"), 1)
        self.assertNotIn("attratus", registry_names)

    def test_variant_ids_are_unique_and_parent_products_exist(self):
        ids = [v["variant_id"] for v in self.variants]
        product_ids = {p["product_id"] for p in CATALOG["products"]}
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(v["product_id"] in product_ids for v in self.variants))


if __name__ == "__main__":
    unittest.main()
