"""Official detail-page evidence for Al Wataniah EDPs."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
EXPECTED = {
    "Lemon Souffle": "https://www.alwataniah.com/products/lemon-souffle",
    "Choco Truffle": "https://www.alwataniah.com/products/choco-truffle",
}


class AlWataniahDetailEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = cls.catalog["products"]
        cls.variants = cls.catalog["variants"]

    def test_two_identities_have_official_100ml_edp_evidence(self):
        for name, url in EXPECTED.items():
            with self.subTest(product=name):
                matches = [
                    p for p in self.products
                    if p.get("brand_name") == "Al Wataniah"
                    and p.get("canonical_name") == name
                ]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertIn(100, product.get("formats_ml", []))
                variants = [
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                    and v.get("size_ml") == 100
                ]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("concentration"), "Eau de Parfum")



    def test_two_more_existing_identities_have_official_100ml_edp_evidence(self):
        expected = {
            "Ameeri": "https://www.alwataniah.com/products/ameeri",
            "Sultan Al Lail": "https://www.alwataniah.com/products/sultan-al-lail",
        }
        for name, url in expected.items():
            with self.subTest(product=name):
                matches = [
                    p for p in self.products
                    if p.get("brand_name") == "Al Wataniah"
                    and p.get("canonical_name") == name
                ]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertIn(100, product.get("formats_ml", []))
                variants = [
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                    and v.get("size_ml") == 100
                ]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("variant_id"), f"SHV-{product['product_id']}-100-000")
                self.assertEqual(variants[0].get("concentration"), "Eau de Parfum")
                self.assertEqual(variants[0].get("source_evidence_url"), url)

if __name__ == "__main__":
    unittest.main()
