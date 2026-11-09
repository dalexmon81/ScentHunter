"""Regression tests for Al Wataniah official product-page identity evidence."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
OFFICIAL_PAGES = {
    "Kayaan Classic": "kayaan-classic",
    "Kayaan Terra": "kayaan-terra",
    "Special Oud": "special-oud",
    "Sabah Al Ward": "sabah-al-ward",
    "Kayaan Gold": "kayaan-gold",
    "Kayaan Midnight": "kayaan-midnight",
    "Ain Emarat": "ain-emarat",
    "Royal Oak I": "royal-oak-i",
    "Al Daiem": "al-daiem",
    "Arya Peony Rose": "arya-peony-rose",
    "Arya": "arya",
    "Ain Emarat Extrait": "ain-emarat-extrait",
    "Sabah Al Ward Sugar": "saba-al-ward-sugar",
    "Royal Oak II": "royal-oak-ii",
    "Al Daiem Elixir": "al-daiem-elixir",
    "Ameerati": "ameerati",
    "Attar Al Wesal": "attar-al-wesal",
    "Praline Toffee": "praline-toffee",
    "Rose Eclat": "rose-eclat"
}

class AlWataniahOfficialStorefrontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = [
            p for p in cls.catalog["products"]
            if p.get("brand_name", p.get("brand")) == "Al Wataniah"
        ]

    def test_individual_official_product_pages_are_recorded(self):
        self.assertEqual(len(OFFICIAL_PAGES), 19)
        for name, slug in OFFICIAL_PAGES.items():
            expected_url = f"https://www.alwataniah.com/products/{slug}"
            with self.subTest(product=name):
                matches = [p for p in self.products if p.get("canonical_name") == name]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), expected_url)
                self.assertEqual(product.get("source_product_url"), expected_url)
                self.assertEqual(product.get("source_evidence_url"), expected_url)

    def test_ain_emarat_and_its_extrait_remain_distinct_identities(self):
        names = {p.get("canonical_name") for p in self.products}
        self.assertIn("Ain Emarat", names)
        self.assertIn("Ain Emarat Extrait", names)
        self.assertNotEqual(
            next(p["product_id"] for p in self.products if p.get("canonical_name") == "Ain Emarat"),
            next(p["product_id"] for p in self.products if p.get("canonical_name") == "Ain Emarat Extrait"),
        )

if __name__ == "__main__":
    unittest.main()
