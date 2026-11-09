"""Official Afnan 9AM/9PM detail-page evidence tests."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
EXPECTED = {
    "9 PM Night Out": {
        "url": "https://www.fr.afnan.com/en/products/9pm-night-out",
        "type": "Extrait de Parfum"
    },
    "9 PM Elixir": {
        "url": "https://www.fr.afnan.com/en/products/9-pm-elixir",
        "type": "Extrait de Parfum"
    },
    "9 PM Pour Femme": {
        "url": "https://www.fr.afnan.com/en/products/9-pm-pour-femme",
        "type": "Eau de Parfum"
    },
    "9 AM": {
        "url": "https://www.fr.afnan.com/en/products/9-am",
        "type": "Eau de Parfum"
    },
    "9 AM Pour Femme": {
        "url": "https://www.fr.afnan.com/en/products/9-am-pour-femme",
        "type": "Eau de Parfum"
    },
    "9 AM Dive": {
        "url": "https://www.fr.afnan.com/en/products/9-am-dive",
        "type": "Eau de Parfum"
    },
    "9 PM Rebel": {
        "url": "https://www.fr.afnan.com/en/products/9-pm-rebel",
        "type": "Eau de Parfum"
    },
    "9 PM": {
        "url": "https://www.fr.afnan.com/en/products/9-pm",
        "type": "Eau de Parfum"
    }
}

class AfnanNineSeriesDetailEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = cls.catalog["products"]
        cls.variants = cls.catalog["variants"]

    def test_eight_nine_series_identities_have_official_detail_evidence(self):
        self.assertEqual(len(EXPECTED), 8)
        for name, evidence in EXPECTED.items():
            with self.subTest(product=name):
                matches = [p for p in self.products if p.get("brand") == "Afnan" and p.get("canonical_name") == name]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), evidence["url"])
                self.assertEqual(product.get("source_product_url"), evidence["url"])
                self.assertEqual(product.get("concentration"), evidence["type"])
                self.assertIn(100, product.get("formats_ml", []))
                matching = [v for v in self.variants if v.get("product_id") == product["product_id"]]
                self.assertEqual(len(matching), 1)
                variant = matching[0]
                self.assertEqual(variant.get("variant_id"), f"SHV-{product['product_id']}-100-000")
                self.assertEqual(variant.get("size_ml"), 100)
                self.assertEqual(variant.get("concentration"), evidence["type"])
                self.assertEqual(variant.get("source_evidence_url"), evidence["url"])

    def test_extrait_and_edp_are_not_collapsed(self):
        for name in ("9 PM Night Out", "9 PM Elixir"):
            product = next(p for p in self.products if p.get("brand") == "Afnan" and p.get("canonical_name") == name)
            self.assertEqual(product.get("concentration"), "Extrait de Parfum")
        for name in ("9 PM", "9 PM Pour Femme", "9 AM", "9 AM Pour Femme", "9 AM Dive", "9 PM Rebel"):
            product = next(p for p in self.products if p.get("brand") == "Afnan" and p.get("canonical_name") == name)
            self.assertEqual(product.get("concentration"), "Eau de Parfum")

if __name__ == "__main__":
    unittest.main()
