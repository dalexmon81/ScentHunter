"""Official Bujairami UAE product-page provenance for recent arrivals."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
EXPECTED = {
    "Tea Splash": ("SH-BUJAIRAMI-TEA-SPLASH", "https://bujairami.ae/products/tea-splash-inspired-by-rain-tea-louis-vuitton", null),
    "V-Luxe": ("SH-BUJAIRAMI-V-LUXE", "https://bujairami.ae/products/v-luxe-inspired-by-libre-vanille-couture-yves-saint-laurent", null),
    "ACE": ("SH-BUJAIRAMI-ACE", "https://bujairami.ae/products/ace-inspired-by-uomo-born-in-roma-coral-fantasy-valentino", null),
    "Last Kingdom": ("SH-BUJAIRAMI-LAST-KINGDOM", "https://bujairami.ae/products/last-kingdom-inspired-by-argentina-memo-paris-extrait", "Extrait de Parfum"),
    "Darkwood": ("SH-BUJAIRAMI-DARKWOOD", "https://bujairami.ae/products/darkwood-inspired-by-chandigarh-express-ex-nihilo-extrait", "Extrait de Parfum"),
    "Chic Wood": ("SH-BUJAIRAMI-CHIC-WOOD", "https://bujairami.ae/products/chic-wood-inspired-by-cedar-chic-carolina-herrera", null),
    "Delulu": ("SH-BUJAIRAMI-DELULU", "https://bujairami.ae/products/delulu-inspired-by-the-hedonist-extrait-de-parfum-ex-nihilo-extrait", "Extrait de Parfum"),
    "Suns Out": ("SH-BUJAIRAMI-SUNS-OUT", "https://bujairami.ae/products/suns-out-inspired-by-my-way-sunny-vanilla-giorgio-armani", null),
}


class BujairamiRecentArrivalEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)

    def test_individual_official_pages_and_concentrations(self):
        for name, (product_id, url, concentration) in EXPECTED.items():
            with self.subTest(name=name):
                matches = [
                    p for p in self.catalog["products"]
                    if p.get("brand") == "Bujairami" and p.get("canonical_name") == name
                ]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product["product_id"], product_id)
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_product_url"], url)
                if concentration:
                    self.assertEqual(product.get("concentration"), concentration)
                else:
                    self.assertNotIn("concentration", product)

    def test_no_unverified_sizes_or_variants_were_created(self):
        ids = {item[0] for item in EXPECTED.values()}
        variants = [v for v in self.catalog.get("variants", []) if v.get("product_id") in ids]
        self.assertEqual(variants, [])


if __name__ == "__main__":
    unittest.main()
