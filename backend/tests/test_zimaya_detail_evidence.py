"""Page-level evidence for the first verified Zimaya fragrance batch."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
EXPECTED = {
    "Cult": "https://zimayaperfumes.com/products/cult",
    "Exquisite": "https://zimayaperfumes.com/products/exquisite",
    "Sharaf Blend": "https://zimayaperfumes.com/products/sharaf-blend-100ml",
    "Grandeur": "https://zimayaperfumes.com/products/grandeur-100ml",
    "Crysta Oud": "https://zimayaperfumes.com/products/crysta-oud-100ml",
    "Farah": "https://zimayaperfumes.com/products/farah",
    "Amber Is Great": "https://zimayaperfumes.com/products/amber-is-great-100ml",
    "Bahjah": "https://zimayaperfumes.com/products/bahja",
    "Wujood": "https://zimayaperfumes.com/products/wujood-100ml",
    "Luxor": "https://zimayaperfumes.com/products/luxor-100ml",
}


class ZimayaDetailEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = cls.catalog["products"]
        cls.variants = cls.catalog["variants"]

    def test_ten_products_have_official_detail_evidence(self):
        for name, url in EXPECTED.items():
            with self.subTest(product=name):
                matches = [
                    p for p in self.products
                    if p.get("brand_name") == "Zimaya"
                    and p.get("canonical_name") == name
                ]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertIn(100, product.get("formats_ml", []))

    def test_each_verified_product_has_one_100ml_edp_variant(self):
        for name in EXPECTED:
            with self.subTest(product=name):
                product = next(
                    p for p in self.products
                    if p.get("brand_name") == "Zimaya"
                    and p.get("canonical_name") == name
                )
                variants = [
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                    and v.get("size_ml") == 100
                ]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("concentration"), "Eau de Parfum")
                for forbidden in ("price", "stock", "shipping_cost", "store_url"):
                    self.assertNotIn(forbidden, variants[0])


if __name__ == "__main__":
    unittest.main()
