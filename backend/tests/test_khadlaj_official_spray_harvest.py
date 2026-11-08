"""Regression tests for the Khadlaj official perfume-spray harvest."""
import json
import unittest
import unicodedata
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
EXPECTED = ["Oud Pure Oud Barakat","Oud Pure Oud Galazaid","Oud Pure Oud Jumeirah","Hareem Al Sultan","Azure Velvet","Maison L'Imaginaire","Saqr Al Badiya","Opus Reborn","Musk Pour Amber","Fursan Brown","Sara","Musk Pure Musk Blend Creation of Iqbal","Le Prestige King","The Proposal Date Night","Le Prestige Royal","Le Prestige Empress","Le Prestige Bold","The Proposal Special Occasion","25 Experience","25 Trust","25 Loyalty","25 Heritage","25 Integrity","Valor Mystique","Valor Honor","Valor Chivalry","Valor Enigma","Empire Empress","Empire Crown","Empire Regent","Karus Blu Spice","Karus Secret Musk","Karus Oud Fire","Karus Amber Gold","Maison Creation De Reve","Maison Epoque Artistique","Maison L'Or Noir","Maison Flor Oud","Wild Indonesian Oud","Mystical Indian Oud Pure","Oud Pour Noble","Musk Pour Narcis","Oud Pour Shaikh","Oud Pour Rouge","Oud Pour Blueberry","Infini Absolute","Cashmere Warm Oud","Cashmere Sunshine Musk","Oud Noir","Sensuous Night","Ombre Notes","Ghadeer Silver","Musk Al Sabah","Oud Al Sabah","Magnate Noble","Magnate Premier","Infini","Shahi Oud","Barwaaz Solid Grey","Rose Couture","Musk Couture"]

class KhadlajOfficialSprayHarvestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)

    @staticmethod
    def normalize(name):
        value = unicodedata.normalize("NFKD", name)
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        return "".join(ch for ch in value.casefold() if ch.isalnum())

    def test_all_harvested_khadlaj_names_present(self):
        names = {self.normalize(p["canonical_name"]) for p in self.catalog["products"] if p.get("brand") == "Khadlaj"}
        for name in EXPECTED:
            with self.subTest(name=name):
                self.assertIn(self.normalize(name), names)

    def test_no_duplicate_product_ids_or_brand_names(self):
        products = self.catalog["products"]
        ids = [p["product_id"] for p in products]
        pairs = [(p.get("brand"), self.normalize(p["canonical_name"])) for p in products]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_harvested_rows_have_explicit_variant_evidence(self):
        harvested = [
            p for p in self.catalog["products"]
            if p["product_id"].startswith("SH-KHADLAJ-SPRAY-HARVEST-")
        ]
        self.assertTrue(harvested)
        for product in harvested:
            with self.subTest(product=product["canonical_name"]):
                self.assertEqual(product["identity_status"], "source_listed_name")
                self.assertEqual(product["source_url"], "https://khadlaj-perfumes.com/collections/perfumes-spray")
                variants = [
                    v for v in self.catalog["variants"]
                    if v.get("product_id") == product["product_id"]
                ]
                self.assertTrue(variants)
                for variant in variants:
                    self.assertTrue(variant.get("source_evidence_url"))
                    self.assertIn(variant.get("size_ml"), product.get("formats_ml", []))

if __name__ == "__main__":
    unittest.main()
