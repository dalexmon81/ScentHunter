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


    def test_twelve_additional_identities_have_official_100ml_edp_evidence(self):
        expected = {
        "Kayaan Midnight": "https://www.alwataniah.com/products/kayaan-midnight",
        "Sabah Al Ward": "https://www.alwataniah.com/products/sabah-al-ward",
        "Sabah Al Ward Sugar": "https://www.alwataniah.com/products/saba-al-ward-sugar",
        "Special Oud": "https://www.alwataniah.com/products/special-oud",
        "Emiran": "https://www.alwataniah.com/products/emiran",
        "Cloud": "https://www.alwataniah.com/products/cloud",
        "Castilla": "https://www.alwataniah.com/products/castilla",
        "Fayroz": "https://www.alwataniah.com/products/fayroz",
        "Layali": "https://www.alwataniah.com/products/layali",
        "Praline Toffee": "https://www.alwataniah.com/products/praline-toffee",
        "Turquois": "https://www.alwataniah.com/products/turquois",
        "Royal Oak II": "https://www.alwataniah.com/products/royal-oak-ii"
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
                self.assertEqual(variants[0].get("concentration"), "Eau de Parfum")
                self.assertEqual(variants[0].get("source_evidence_url"), url)


    def test_ten_more_existing_identities_have_official_100ml_edp_evidence(self):
        expected = {
        "Kayaan Classic": "https://www.alwataniah.com/products/kayaan-classic",
        "Kayaan Terra": "https://www.alwataniah.com/products/kayaan-terra",
        "Kayaan Gold": "https://www.alwataniah.com/products/kayaan-gold",
        "Ain Emarat": "https://www.alwataniah.com/products/ain-emarat",
        "Royal Oak I": "https://www.alwataniah.com/products/royal-oak-i",
        "Al Daiem": "https://www.alwataniah.com/products/al-daiem",
        "Arya Peony Rose": "https://www.alwataniah.com/products/arya-peony-rose",
        "Arya": "https://www.alwataniah.com/products/arya",
        "Ain Emarat Extrait": "https://www.alwataniah.com/products/ain-emarat-extrait",
        "Nada": "https://www.alwataniah.com/products/nada"
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
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertIn(100, product.get("formats_ml", []))
                variants = [
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                    and v.get("size_ml") == 100
                ]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("concentration"), "Eau de Parfum")
                self.assertEqual(variants[0].get("source_evidence_url"), url)

if __name__ == "__main__":
    unittest.main()
