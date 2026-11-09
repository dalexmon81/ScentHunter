"""Regression coverage for the Aromatix official French Avenue catalog pages."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
EXPECTED = {
    "Carnal Desire": ("https://frenchavenue.com/products/carnal-desire", "Eau de Parfum"),
    "Forbidden Fruit": ("https://frenchavenue.com/products/aromatix-forbidden-fruit", "Eau de Parfum"),
    "Frostbite": ("https://frenchavenue.com/products/aromatix-frostbite", "Extrait de Parfum"),
    "Magnetiq": ("https://frenchavenue.com/products/aromatix-magnetiq", "Eau de Parfum"),
    "Naughty Dates": ("https://frenchavenue.com/products/aromatix-naughty-dates", "Eau de Parfum"),
    "Platine Blanc": ("https://frenchavenue.com/products/aromatix-plantine-blanc", None),
    "Royal Taboo": ("https://frenchavenue.com/products/royal-taboo", "Extrait de Parfum"),
    "Sun Kissed": ("https://frenchavenue.com/products/aromatix-sunkissed", "Eau de Parfum"),
    "Teas Me": ("https://frenchavenue.com/products/aromatix-teas-me", "Eau de Parfum"),
    "X Xandal": ("https://frenchavenue.com/products/aromatix-x-xandal", "Extrait de Parfum"),
}


class AromatixOfficialCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = {
            row["canonical_name"]: row for row in cls.catalog["products"]
            if row.get("brand_name") == "Aromatix"
        }

    def test_ten_official_collection_fragrances_have_individual_page_provenance(self):
        for name, (url, concentration) in EXPECTED.items():
            with self.subTest(name=name):
                self.assertIn(name, self.products)
                row = self.products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), url)
                self.assertEqual(row.get("source_product_url"), url)
                if concentration is None:
                    self.assertNotIn("concentration", row)
                    self.assertNotIn("formats_ml", row)
                    self.assertFalse(any(v.get("product_id") == row["product_id"] for v in self.catalog["variants"]))
                else:
                    self.assertEqual(row.get("concentration"), concentration)
                    self.assertIn(100, row.get("formats_ml", []))
                    matches = [
                        v for v in self.catalog["variants"]
                        if v.get("product_id") == row["product_id"] and v.get("size_ml") == 100
                    ]
                    self.assertEqual(len(matches), 1)
                    self.assertEqual(matches[0].get("concentration"), concentration)
                    self.assertEqual(matches[0].get("source_evidence_url"), url)

    def test_bundle_products_are_not_added_as_standalone_fragrances(self):
        names = {row.get("canonical_name") for row in self.products.values()}
        self.assertNotIn("Aromatix Summer Vibes Blue", names)
        self.assertNotIn("Aromatix Summer Vibes Yellow", names)


if __name__ == "__main__":
    unittest.main()
