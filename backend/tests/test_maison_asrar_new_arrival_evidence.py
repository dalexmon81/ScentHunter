"""Individual official product-page evidence for Maison Asrar new arrivals.

The inspected pages confirm standalone fragrance identities and names. They do not
publish a machine-readable size or concentration in the page content inspected here,
so this test deliberately does not require or invent variants.
"""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
EXPECTED = {
    "Ameer": "https://maisonasrar.com/products/ameer",
    "DXB Jumeirah": "https://maisonasrar.com/products/dxb-jumeirah",
    "Last Swim": "https://maisonasrar.com/products/last-swim",
    "Silent Surge": "https://maisonasrar.com/products/silent-surge",
    "Veyra": "https://maisonasrar.com/products/veyra",
    "Infina": "https://maisonasrar.com/products/infina",
    "Librae": "https://maisonasrar.com/products/librae",
    "Harmony": "https://maisonasrar.com/products/harmony",
    "Fairyland": "https://maisonasrar.com/products/fairyland",
    "Whisper": "https://maisonasrar.com/products/whisper",
    "Dubai Milano": "https://maisonasrar.com/products/dubai-milano",
    "Dubai London": "https://maisonasrar.com/products/dubai-london",
    "Dubai Miami": "https://maisonasrar.com/products/dubai-miami",
    "III Thriller": "https://maisonasrar.com/products/iii-thriller",
    "Milky Way": "https://maisonasrar.com/products/milky-way",
    "Muharib": "https://maisonasrar.com/products/muharib",
    "Faris Al Arab": "https://maisonasrar.com/products/faris-al-arab",
    "Vanilla Seduction": "https://maisonasrar.com/products/vanilla-seduction",
    "Vanilla Aura": "https://maisonasrar.com/products/vanilla-aura",
    "Throne Eclipse": "https://maisonasrar.com/products/throne-eclipse",
    "Throne": "https://maisonasrar.com/products/throne",
    "Khayyal": "https://maisonasrar.com/products/khayyal",
    "Hikaya": "https://maisonasrar.com/products/hikaya",
    "Hilm": "https://maisonasrar.com/products/hilm",
    "Cascade": "https://maisonasrar.com/products/cascade",
    "Tornado": "https://maisonasrar.com/products/tornado",
    "Wadi": "https://maisonasrar.com/products/wadi",
    "DXB": "https://maisonasrar.com/products/dxb",
    "Vanilla Voyage": "https://maisonasrar.com/products/vanilla-voyage-eau-de-parfum",
    "Vision": "https://maisonasrar.com/products/vision",
    "Oh Honey!": "https://maisonasrar.com/products/oh-honey-eau-de-parfum",
}


class MaisonAsrarNewArrivalEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)

    def test_new_arrival_names_use_individual_official_detail_pages(self):
        products = [
            p for p in self.catalog["products"]
            if p.get("brand") == "Maison Asrar"
        ]
        for name, url in EXPECTED.items():
            with self.subTest(product=name):
                matches = [p for p in products if p.get("canonical_name") == name]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)

    def test_no_unverified_variants_or_commercial_data_were_added(self):
        product_ids = {
            p["product_id"] for p in self.catalog["products"]
            if p.get("brand") == "Maison Asrar"
            and p.get("canonical_name") in EXPECTED
        }
        variants = [
            v for v in self.catalog.get("variants", [])
            if v.get("product_id") in product_ids
        ]
        self.assertEqual(variants, [])
        for product in self.catalog["products"]:
            if product.get("product_id") in product_ids:
                self.assertNotIn("price", product)
                self.assertNotIn("stock", product)


if __name__ == "__main__":
    unittest.main()
