"""Additional official product-page evidence for Al Wataniah identities."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
DETAILS = {
    "Kayaan Classic": "https://www.alwataniah.com/products/kayaan-classic",
    "Sabah Al Ward": "https://www.alwataniah.com/products/sabah-al-ward",
    "Sabah Al Ward Sugar": "https://www.alwataniah.com/products/saba-al-ward-sugar",
    "Ain Emarat": "https://www.alwataniah.com/products/ain-emarat",
    "Ain Emarat Extrait": "https://www.alwataniah.com/products/ain-emarat-extrait",
    "Royal Oak I": "https://www.alwataniah.com/products/royal-oak-i",
}
VERIFIED_100ML_EDP = {"Sabah Al Ward", "Sabah Al Ward Sugar"}


class AlWataniahAdditionalDetailEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = cls.catalog["products"]
        cls.variants = cls.catalog["variants"]

    def test_official_detail_pages_upgrade_existing_identities(self):
        for name, url in DETAILS.items():
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
                self.assertEqual(product.get("source_evidence_url"), url)

    def test_only_explicitly_documented_100ml_edp_details_create_variants(self):
        alwataniah_ids = {
            p["product_id"] for p in self.products
            if p.get("brand_name") == "Al Wataniah"
        }
        variants = [v for v in self.variants if v.get("product_id") in alwataniah_ids]
        for name in VERIFIED_100ML_EDP:
            with self.subTest(product=name):
                product = next(
                    p for p in self.products
                    if p.get("brand_name") == "Al Wataniah"
                    and p.get("canonical_name") == name
                )
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertEqual(product.get("formats_ml"), [100])
                matching = [
                    v for v in variants
                    if v.get("product_id") == product["product_id"]
                    and v.get("size_ml") == 100
                    and v.get("concentration") == "Eau de Parfum"
                ]
                self.assertEqual(len(matching), 1)

    def test_other_detail_pages_do_not_infer_size_or_concentration(self):
        for name in set(DETAILS) - VERIFIED_100ML_EDP:
            with self.subTest(product=name):
                product = next(
                    p for p in self.products
                    if p.get("brand_name") == "Al Wataniah"
                    and p.get("canonical_name") == name
                )
                self.assertNotIn("concentration", product)
                self.assertNotIn("formats_ml", product)
                self.assertFalse([
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                ])


if __name__ == "__main__":
    unittest.main()
