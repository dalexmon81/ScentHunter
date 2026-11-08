"""Guard official Al Wataniah product-page evidence and explicit variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Milele": "https://www.alwataniah.com/products/milele",
    "Turquois": "https://www.alwataniah.com/products/turquois",
    "Cloud": "https://www.alwataniah.com/products/cloud",
    "Sabah Al Ward": "https://www.alwataniah.com/products/sabah-al-ward",
    "Ain Emarat": "https://www.alwataniah.com/products/ain-emarat",
    "Arya": "https://www.alwataniah.com/products/arya",
    "Royal Oak I": "https://www.alwataniah.com/products/royal-oak-i",
    "Al Daiem": "https://www.alwataniah.com/products/al-daiem",
}


class AlWataniahOfficialDetailEvidenceTests(unittest.TestCase):
    def test_selected_products_use_official_detail_pages(self):
        rows = [
            row for row in CATALOG.get("products", [])
            if (row.get("brand_name") or row.get("brand") or "").strip() == "Al Wataniah"
        ]
        for name, expected_url in EXPECTED.items():
            with self.subTest(product=name):
                matches = [
                    row for row in rows
                    if (row.get("canonical_name") or row.get("name")) == name
                ]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("source_url"), expected_url)
                self.assertEqual(product.get("source_product_url"), expected_url)
                self.assertEqual(product.get("source_evidence_url"), expected_url)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertEqual(product.get("formats_ml"), [100])

    def test_each_verified_product_has_one_matching_explicit_variant(self):
        products = {
            row["canonical_name"]: row
            for row in CATALOG.get("products", [])
            if row.get("brand") == "Al Wataniah"
        }
        variants = CATALOG.get("variants", [])
        for name in EXPECTED:
            with self.subTest(product=name):
                product = products[name]
                matches = [
                    variant for variant in variants
                    if variant.get("product_id") == product["product_id"]
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].get("size_ml"), 100)
                self.assertEqual(matches[0].get("concentration"), "Eau de Parfum")


if __name__ == "__main__":
    unittest.main()
