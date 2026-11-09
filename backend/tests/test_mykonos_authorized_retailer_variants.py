"""Regression coverage for Mykonos variants verified on authorized EU product pages.

The brand-owned collection URL remains in source_url. source_evidence_url records
the individual authorized-retailer product page used for size/concentration
evidence; it is not misrepresented as a brand-owned URL.
"""
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "backend" / "product_catalog.json"

EXPECTED = {
    "Only You": [(100, "Eau de Parfum")],
    "Shades Perfume": [(100, None)],
    "Chai Crema Latte": [(50, "Extrait de Parfum")],
    "Jynx": [(100, "Eau de Parfum")],
    "Rouge": [(50, "Eau de Parfum")],
    "Seven Roses": [(50, "Eau de Parfum")],
    "Ivory": [(50, "Eau de Parfum")],
    "Blossom": [(50, "Eau de Parfum")],
    "Zora": [(50, "Eau de Parfum"), (100, "Eau de Parfum")],
    "Down to Earth": [(50, "Extrait de Parfum")],
    "When in Paris": [(50, "Extrait de Parfum")],
    "Pandan Sticky Rice": [(50, "Eau de Parfum")],
    "Pistachio Cream Cake": [(50, "Eau de Parfum")],
    "Blaze": [(50, "Eau de Parfum")],
    "Memoir of Meri": [(50, "Extrait de Parfum")],
    "Once Upon Don": [(50, "Extrait de Parfum")],
}


class MykonosAuthorizedRetailerVariantEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        cls.products = {
            p["canonical_name"]: p
            for p in cls.catalog["products"]
            if p.get("brand_name") == "Mykonos"
        }
        cls.variants = cls.catalog["variants"]

    def test_each_existing_identity_has_documented_variant_evidence(self):
        for name, expected_variants in EXPECTED.items():
            with self.subTest(product=name):
                product = self.products[name]
                self.assertEqual(
                    product["source_url"],
                    "https://officialmykonos.com/collections/all",
                )
                self.assertTrue(
                    product.get("source_evidence_url", "").startswith(
                        "https://mykonosperfumes.eu/products/"
                    )
                )
                actual = [
                    (v["size_ml"], v.get("concentration"))
                    for v in self.variants
                    if v.get("product_id") == product["product_id"]
                ]
                for expected in expected_variants:
                    self.assertIn(expected, actual)

    def test_shades_concentration_is_not_inferred(self):
        product = self.products["Shades Perfume"]
        variants = [
            v for v in self.variants
            if v.get("product_id") == product["product_id"]
        ]
        self.assertEqual(len(variants), 1)
        self.assertNotIn("concentration", variants[0])

    def test_no_duplicate_variant_ids(self):
        ids = [v["variant_id"] for v in self.variants]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
