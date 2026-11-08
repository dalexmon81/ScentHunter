"""Regression coverage for Ministry of Oud official catalog identities and 100 ml variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Ministry of Oud - Amber Oud": ("ministry-of-oud-amber-oud", True),
    "Ministry of Oud - Gladiators Oath": ("ministry-of-oud-gladiators-oath", False),
    "Ministry of Oud - Maestro's Symphony": ("ministry-of-oud-maestro-s-symphony", False),
    "Ministry of Oud - Nile Whispers": ("ministry-of-oud-nile-whispers", False),
    "Ministry of Oud - Oud Beyond the Wall": ("ministry-of-oud-oud-beyond-the-wall", False),
    "Ministry of Oud - Oud Indonesian": ("ministry-of-oud-oud-indonesian", True),
    "Ministry of Oud - Oud Royal": ("ministry-of-oud-oud-royal", True),
    "Ministry of Oud - Oud Satin": ("ministry-of-oud-oud-satin", False),
    "Ministry of Oud - Romance Reverie": ("ministry-of-oud-romance-reverie", False),
    "Ministry of Oud - Strictly Oud": ("ministry-of-oud-strictly-oud", True),
    "Ministry of Oud Greatest": ("ministry-of-oud-greatest", True),
}


class ParisCornerMinistryOfOudTests(unittest.TestCase):
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

    def test_all_eleven_official_fragrances_have_canonical_identities(self):
        for name, (slug, is_edp) in EXPECTED.items():
            with self.subTest(product=name):
                product = self.products[name]
                url = f"https://www.pariscornerperfumes.com/products/{slug}"
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertEqual(product["collection_name"], "Ministry of Oud")
                self.assertEqual(product["formats_ml"], [100])
                if is_edp:
                    self.assertEqual(product["concentration"], "Eau de Parfum")
                else:
                    self.assertNotIn("concentration", product)

    def test_each_identity_has_one_100ml_variant(self):
        for name, (_slug, is_edp) in EXPECTED.items():
            with self.subTest(product=name):
                product = self.products[name]
                matches = [
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                    and v.get("size_ml") == 100
                ]
                self.assertEqual(len(matches), 1)
                if is_edp:
                    self.assertEqual(matches[0]["concentration"], "Eau de Parfum")
                else:
                    self.assertNotIn("concentration", matches[0])

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
