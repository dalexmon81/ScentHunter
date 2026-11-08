"""Official product-page evidence for the Maison Asrar Royal Collection."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
EXPECTED = {
    "Belgravia": "https://maisonasrar.com/products/belgravia",
    "Legacy": "https://maisonasrar.com/products/legacy",
    "Vanguard": "https://maisonasrar.com/products/vanguard",
    "Regent": "https://maisonasrar.com/products/regent",
    "Majesty": "https://maisonasrar.com/products/majesty",
    "Monarch": "https://maisonasrar.com/products/maison-asrar-monarch-eau-de-parfum",
    "Heritage": "https://maisonasrar.com/products/maison-asrar-heritage-eau-de-parfum-100-ml-unisex",
    "Imperial": "https://maisonasrar.com/products/maison-asrar-imperial-eau-de-parfum",
    "Treasure": "https://maisonasrar.com/products/maison-asrar-treasure-eau-de-parfum-100-ml-unisex",
}


class MaisonAsrarRoyalCollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)

    def test_nine_royal_collection_names_have_official_detail_pages(self):
        products = [
            p for p in self.catalog["products"]
            if p.get("brand_name") == "Maison Asrar"
        ]
        for name, url in EXPECTED.items():
            with self.subTest(product=name):
                matches = [p for p in products if p.get("canonical_name") == name]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("collection_name"), "Royal Collection")

    def test_no_unverified_sizes_or_commercial_offers_were_added(self):
        royal_names = set(EXPECTED)
        royal_products = [
            p for p in self.catalog["products"]
            if p.get("brand_name") == "Maison Asrar"
            and p.get("canonical_name") in royal_names
        ]
        self.assertEqual(len(royal_products), 9)
        for product in royal_products:
            self.assertNotIn("price", product)
            self.assertNotIn("stock", product)


if __name__ == "__main__":
    unittest.main()
