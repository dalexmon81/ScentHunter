"""Regression tests for Afnan official global product detail pages."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
OFFICIAL_PAGES = {
    "9 PM": "9-pm",
    "9 PM Pour Femme": "9-pm-pour-femme",
    "9 PM Elixir": "9-pm-elixir",
    "9 PM Rebel": "9-pm-rebel",
    "ABIYAD MUKHALLAT": "mukhallat-abiyad",
    "ABIYAD MUSK": "musk-abiyad-cpo",
    "ABIYAD SANDAL": "sandal-abiyad",
    "ADWAA AL SHARQ": "adwaa-al-sharq",
    "Cherry Bouquet": "cherry-bouquet",
    "Delicious Bouquet": "delicious-bouquet",
    "Ebdaa Concentrated Perfume Oil": "ebdaa-perfume-oil",
    "EDICT AMBERYTHME": "edict-amberythme",
    "EDICT MUSCTIQUE": "edict-musctique",
    "EDICT OUDDICTION": "edict-ouddiction",
    "Historic Doria": "historic-doria"
}

class AfnanOfficialGlobalStorefrontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = [
            p for p in cls.catalog["products"]
            if p.get("brand_name", p.get("brand")) == "Afnan"
        ]

    def test_individual_official_pages_are_recorded_once(self):
        self.assertEqual(len(OFFICIAL_PAGES), 15)
        for name, slug in OFFICIAL_PAGES.items():
            url = f"https://afnan.com/products/{slug}"
            with self.subTest(product=name):
                matches = [p for p in self.products if p.get("canonical_name") == name]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)

    def test_oils_are_not_confused_with_deodorants_or_sets(self):
        oil_names = {"ABIYAD MUKHALLAT", "ABIYAD MUSK", "ABIYAD SANDAL", "ADWAA AL SHARQ", "Ebdaa Concentrated Perfume Oil"}
        self.assertTrue(oil_names.issubset({p.get("canonical_name") for p in self.products}))
        self.assertFalse(any("DEO" in p.get("canonical_name", "").upper() for p in self.products))

if __name__ == "__main__":
    unittest.main()
