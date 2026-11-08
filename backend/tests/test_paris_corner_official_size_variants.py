"""Regression coverage for Paris Corner official 100 ml size evidence."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Caramel Bash": "https://www.pariscornerperfumes.com/products/caramel-bash-1",
    "Dusky Vanilla": "https://www.pariscornerperfumes.com/products/dusky-vanilla",
    "Fig Fete": "https://www.pariscornerperfumes.com/products/fig-fete",
    "Khair Peach Delulu": "https://www.pariscornerperfumes.com/products/khair-peach-delulu",
}


class ParisCornerOfficialSizeVariantTests(unittest.TestCase):
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
        for name, url in EXPECTED.items():
            with self.subTest(product=name):
                product = self.products[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertIn(100, product["formats_ml"])
                matches = [
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                    and v.get("size_ml") == 100
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]["source_url"], url)
                # The official detail pages confirm size, but the retrieved
                # page content does not explicitly state concentration.
                self.assertNotIn("concentration", matches[0])

    def test_family_registry_formats_are_aligned(self):
        for name in EXPECTED:
            with self.subTest(product=name):
                product = next(p for p in self.family["products"] if p["canonical_name"] == name)
                self.assertIn(100, product.get("formats_ml", []))

    def test_variant_ids_are_unique_and_parent_products_exist(self):
        ids = [v["variant_id"] for v in self.variants]
        product_ids = {p["product_id"] for p in CATALOG["products"]}
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(v["product_id"] in product_ids for v in self.variants))


if __name__ == "__main__":
    unittest.main()
