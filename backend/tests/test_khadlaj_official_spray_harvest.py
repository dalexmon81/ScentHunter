"""Regression tests for the Khadlaj official perfume-spray harvest."""
import json
import unittest
import unicodedata
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
VERIFIED_DETAIL_IDS = {
    "SH-KHADLAJ-SPRAY-HARVEST-056",
    "SH-KHADLAJ-SPRAY-HARVEST-057",
    "SH-KHADLAJ-SPRAY-HARVEST-058",
    "SH-KHADLAJ-SPRAY-HARVEST-064",
    "SH-KHADLAJ-SPRAY-HARVEST-065",
    "SH-KHADLAJ-SPRAY-HARVEST-066",
    "SH-KHADLAJ-SPRAY-HARVEST-082",
    "SH-KHADLAJ-SPRAY-HARVEST-070",
    "SH-KHADLAJ-SPRAY-HARVEST-071",
    "SH-KHADLAJ-SPRAY-HARVEST-072",
    "SH-KHADLAJ-SPRAY-HARVEST-083",
    "SH-KHADLAJ-SPRAY-HARVEST-084",
    "SH-KHADLAJ-SPRAY-HARVEST-085",
    "SH-KHADLAJ-SPRAY-HARVEST-076",
    "SH-KHADLAJ-SPRAY-HARVEST-077",
    "SH-KHADLAJ-SPRAY-HARVEST-078",
}

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

    def test_unreconciled_rows_remain_name_only_and_verified_rows_are_upgraded(self):
        for product in self.catalog["products"]:
            if not product["product_id"].startswith("SH-KHADLAJ-SPRAY-HARVEST-"):
                continue
            if product["product_id"] in VERIFIED_DETAIL_IDS:
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertTrue(product["source_url"].startswith("https://khadlaj-perfumes"))
                self.assertIn("concentration", product)
                self.assertTrue(product.get("formats_ml"))
                self.assertEqual(
                    len([v for v in self.catalog["variants"] if v.get("product_id") == product["product_id"]]),
                    1,
                )
                continue
            self.assertEqual(product["identity_status"], "source_listed_name")
            self.assertEqual(product["source_url"], "https://khadlaj-perfumes.com/collections/perfumes-spray")
            self.assertNotIn("concentration", product)
            self.assertNotIn("formats_ml", product)

if __name__ == "__main__":
    unittest.main()
