"""Regression tests for official Afnan and Armaf variants."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
EXPECTED = [
    ("Afnan", "9 AM", 100, "Eau de Parfum", "https://fr.afnan.com/products/9-am"),
    ("Afnan", "9 AM Pour Femme", 100, "Eau de Parfum", "https://fr.afnan.com/products/9-am-pour-femme"),
    ("Afnan", "Rare", 100, "Eau de Parfum", "https://fr.afnan.com/products/rare"),
    ("Afnan", "Supremacy Gold", 100, "Eau de Parfum", "https://fr.afnan.com/products/supremacy-gold"),
    ("Afnan", "Stardust", 100, "Extrait de Parfum", "https://us.afnan.com/products/stardust"),
    ("Armaf", "Luna", 100, "Eau de Parfum", "https://cz.armaf.eu/products/luna"),
    ("Armaf", "Miss Armaf Attitude", 100, "Eau de Parfum", "https://cz.armaf.eu/products/miss-armaf-attitude"),
    ("Armaf", "Miss Armaf Grandeur", 100, "Eau de Parfum", "https://cz.armaf.eu/products/miss-armaf-grandeur"),
    ("Armaf", "Odyssey Candee Special Edition", 60, "Eau de Parfum", "https://cz.armaf.eu/en/products/odyssey-candee-special-edition"),
    ("Armaf", "Odyssey Candee Special Edition", 100, "Eau de Parfum", "https://cz.armaf.eu/en/products/odyssey-candee-special-edition"),
    ("Armaf", "Odyssey Candee Special Edition", 200, "Eau de Parfum", "https://cz.armaf.eu/en/products/odyssey-candee-special-edition"),
    ("Armaf", "The Pride of Armaf Pour Homme", 100, "Eau de Parfum", "https://armaf.com/products/the-pride-of-armaf-pour-homme"),
]

class OfficialAfnanArmafVariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    def test_each_official_page_maps_to_one_existing_product_variant(self):
        for brand, name, size, concentration, source in EXPECTED:
            with self.subTest(brand=brand, name=name, size=size):
                products = [p for p in self.catalog["products"] if p.get("brand") == brand and p.get("canonical_name") == name]
                self.assertEqual(len(products), 1)
                product = products[0]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), source)
                self.assertIn(size, product.get("formats_ml", []))
                variants = [v for v in self.catalog["variants"] if v.get("product_id") == product["product_id"] and v.get("size_ml") == size and v.get("concentration") == concentration]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("source_evidence_url"), source)
                for key in ("price", "currency", "availability", "stock", "offer_url", "retailer"):
                    self.assertNotIn(key, variants[0])

    def test_variant_ids_unique_and_references_valid(self):
        variants = self.catalog["variants"]
        self.assertEqual(len(variants), len({v.get("variant_id") for v in variants}))
        parent_ids = {p.get("product_id") for p in self.catalog["products"]}
        self.assertTrue(all(v.get("product_id") in parent_ids for v in variants))

if __name__ == "__main__":
    unittest.main()
