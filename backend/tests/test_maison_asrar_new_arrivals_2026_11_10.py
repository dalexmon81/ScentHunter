"""Regression coverage for the twelve Maison Asrar official New Arrivals entries."""

import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
EXPECTED = {
    "Ameer": "https://maisonasrar.com/products/ameer",
    "Belgravia": "https://maisonasrar.com/products/belgravia",
    "DXB Jumeirah": "https://maisonasrar.com/products/dxb-jumeirah",
    "Last Swim": "https://maisonasrar.com/products/last-swim",
    "Silent Surge": "https://maisonasrar.com/products/silent-surge",
    "Regent": "https://maisonasrar.com/products/regent",
    "Veyra": "https://maisonasrar.com/products/veyra",
    "Infina": "https://maisonasrar.com/products/infina",
    "Librae": "https://maisonasrar.com/products/librae",
    "Harmony": "https://maisonasrar.com/products/harmony",
    "Fairyland": "https://maisonasrar.com/products/fairyland",
    "Whisper": "https://maisonasrar.com/products/whisper",
}


class MaisonAsrarNewArrivalsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = [
            row for row in cls.catalog.get("products", [])
            if row.get("brand_name") == "Maison Asrar"
        ]

    def test_all_official_new_arrivals_have_one_canonical_identity(self):
        for name, url in EXPECTED.items():
            with self.subTest(name=name):
                matching = [
                    row for row in self.products
                    if row.get("canonical_name") == name
                ]
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0].get("identity_status"), "source_verified_name")
                self.assertEqual(matching[0].get("source_url"), url)
                self.assertEqual(matching[0].get("source_product_url"), url)
                self.assertEqual(matching[0].get("source_evidence_url"), url)

    def test_no_new_arrival_is_misclassified_as_a_non_perfume_category(self):
        excluded_terms = ("room spray", "reed diffuser", "body mist", "deodorant", "lotion")
        for name in EXPECTED:
            with self.subTest(name=name):
                row = next(
                    row for row in self.products
                    if row.get("canonical_name") == name
                )
                text = " ".join(str(row.get(key, "")) for key in ("canonical_name", "name", "family_name")).lower()
                self.assertFalse(any(term in text for term in excluded_terms))


if __name__ == "__main__":
    unittest.main()
