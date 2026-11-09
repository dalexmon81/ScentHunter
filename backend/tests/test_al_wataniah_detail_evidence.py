"""Official detail-page evidence for Al Wataniah EDPs."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
EXPECTED = {
    "Abyat": "https://www.alwataniah.com/products/abyat",
    "Ain Emarat": "https://www.alwataniah.com/products/ain-emarat",
    "Ain Emarat Extrait": "https://www.alwataniah.com/products/ain-emarat-extrait",
    "Al Daiem": "https://www.alwataniah.com/products/al-daiem",
    "Al Daiem Elixir": "https://www.alwataniah.com/products/al-daiem-elixir",
    "Al Layl": "https://www.alwataniah.com/products/al-layl",
    "Alya": "https://www.alwataniah.com/products/alya",
    "Ameerati": "https://www.alwataniah.com/products/ameerati",
    "Ameeri": "https://www.alwataniah.com/products/ameeri",
    "Arya": "https://www.alwataniah.com/products/arya",
    "Arya Peony Rose": "https://www.alwataniah.com/products/arya-peony-rose",
    "Attar Al Wesal": "https://www.alwataniah.com/products/attar-al-wesal",
    "Baraa": "https://www.alwataniah.com/products/baraa",
    "Bareeq Al Dhahab": "https://www.alwataniah.com/products/bareeq-al-dhahab",
    "Brownie Bite": "https://www.alwataniah.com/products/brownie-bite",
    "Castilla": "https://www.alwataniah.com/products/castilla",
    "Choco Truffle": "https://www.alwataniah.com/products/choco-truffle",
    "Cloud": "https://www.alwataniah.com/products/cloud",
    "Emiran": "https://www.alwataniah.com/products/emiran",
    "Fayroz": "https://www.alwataniah.com/products/fayroz",
    "Golden Honey": "https://www.alwataniah.com/products/golden-honey",
    "Kayaan Classic": "https://www.alwataniah.com/products/kayaan-classic",
    "Kayaan Gold": "https://www.alwataniah.com/products/kayaan-gold",
    "Kayaan Midnight": "https://www.alwataniah.com/products/kayaan-midnight",
    "Kayaan Terra": "https://www.alwataniah.com/products/kayaan-terra",
    "Layali": "https://www.alwataniah.com/products/layali",
    "Lemon Souffle": "https://www.alwataniah.com/products/lemon-souffle",
    "Nada": "https://www.alwataniah.com/products/nada",
    "Oud Mystery Intense": "https://www.alwataniah.com/products/oud-mystery-intense",
    "Praline Toffee": "https://www.alwataniah.com/products/praline-toffee",
    "Rose Eclat": "https://www.alwataniah.com/products/rose-eclat",
    "Rose Mystery Intense": "https://www.alwataniah.com/products/rose-mystery-intense",
    "Royal Oak I": "https://www.alwataniah.com/products/royal-oak-i",
    "Royal Oak II": "https://www.alwataniah.com/products/royal-oak-ii",
    "Sabah Al Ward": "https://www.alwataniah.com/products/sabah-al-ward",
    "Sabah Al Ward Sugar": "https://www.alwataniah.com/products/saba-al-ward-sugar",
    "Sahari": "https://www.alwataniah.com/products/sahari",
    "Special Oud": "https://www.alwataniah.com/products/special-oud",
    "Sultan Al Lail": "https://www.alwataniah.com/products/sultan-al-lail",
    "Turquois": "https://www.alwataniah.com/products/turquois"
}

class AlWataniahDetailEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = cls.catalog["products"]
        cls.variants = cls.catalog["variants"]

    def test_all_forty_identities_have_official_100ml_edp_evidence(self):
        self.assertEqual(len(EXPECTED), 40)
        for name, url in EXPECTED.items():
            with self.subTest(product=name):
                matches = [p for p in self.products if p.get("brand_name") == "Al Wataniah" and p.get("canonical_name") == name]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertIn(100, product.get("formats_ml", []))
                matching = [v for v in self.variants if v.get("product_id") == product["product_id"]]
                self.assertEqual(len(matching), 1)
                variant = matching[0]
                self.assertEqual(variant.get("size_ml"), 100)
                self.assertEqual(variant.get("concentration"), "Eau de Parfum")
                self.assertEqual(variant.get("source_evidence_url"), url)

if __name__ == "__main__":
    unittest.main()
