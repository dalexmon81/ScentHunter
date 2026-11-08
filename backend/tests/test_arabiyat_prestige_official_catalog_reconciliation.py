"""Regression tests for official Arabiyat Prestige Al Youm and Red Oud pages."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Attar Al Youm Black": "https://arabiyatprestige.com/products/attar-al-youm-edp-100ml-1",
    "Musk Al Youm": "https://arabiyatprestige.com/collections/arabiyat-prestige/products/musk-al-youm-edp-100ml-1",
    "Oud Al Youm": "https://arabiyatprestige.com/products/oud-al-youm-edp-100ml-1",
    "Red Oud": "https://arabiyatprestige.com/products/red-oud-edp-100ml-1",
    "Al Shujae": "https://arabiyatprestige.com/products/al-shujae-edp-100-ml"
}


class ArabiyatPrestigeOfficialCatalogReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = {
            p["canonical_name"]: p
            for p in CATALOG["products"]
            if p.get("brand_name") == "Arabiyat Prestige"
        }
        cls.variants = CATALOG["variants"]
        cls.family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "arabiyat_prestige_catalog"
        )

    def test_five_missing_identities_have_individual_official_pages(self):
        for name, url in EXPECTED.items():
            with self.subTest(product=name):
                product = self.products[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertEqual(product["source_product_url"], url)
                self.assertEqual(product["formats_ml"], [100])
                self.assertEqual(product["concentration"], "Eau de Parfum")

    def test_each_identity_has_one_100ml_edp_variant(self):
        for name, url in EXPECTED.items():
            with self.subTest(product=name):
                product = self.products[name]
                matches = [
                    v for v in self.variants
                    if v["product_id"] == product["product_id"]
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]["size_ml"], 100)
                self.assertEqual(matches[0]["concentration"], "Eau de Parfum")
                self.assertEqual(matches[0]["source_url"], url)

    def test_registry_formats_are_aligned(self):
        for name in EXPECTED:
            with self.subTest(product=name):
                row = next(p for p in self.family["products"] if p["canonical_name"] == name)
                self.assertIn(100, row.get("formats_ml", []))

    def test_product_and_variant_ids_are_unique(self):
        product_ids = [p["product_id"] for p in CATALOG["products"]]
        variant_ids = [v["variant_id"] for v in self.variants]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))


if __name__ == "__main__":
    unittest.main()
