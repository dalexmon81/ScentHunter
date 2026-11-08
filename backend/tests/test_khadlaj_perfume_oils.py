"""Regression tests for Khadlaj official perfume oils and Dehn Al Oudh."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

OFFICIAL_OILS = {
    "Maya": 20,
    "Johayna Purple": 20,
    "Amber Pure": 20,
    "Arabian Treasure": 20,
    "Anabia Red": 20,
    "Anabia Blue": 20,
    "Oud & Musk": 20,
    "Pure Musk": 20,
    "Johayna Green": 20,
    "Kayaan Silver": 20,
    "Kayaan Gold": 20,
    "Pink Musk": 20,
    "Purple Musk": 20,
    "Malika Red": 20,
    "Malika Green": 20,
    "Hareem Al Sultan Blue": 35,
    "Hareem Al Sultan Gold": 35,
    "Hareem Al Sultan Silver": 35,
    "Mukhalath Ma'a Ward Taiba": 12,
    "Rimaal Brown": 15,
    "Rimaal Green": 15,
    "Haneen Gold": 20,
    "Haneen Rose Gold": 20,
    "Jameel": 25,
    "Zainab": 18,
    "Roohi Wa Roohak Gold": 20,
    "Shamookh Gold": 20,
    "Alf Wardaat": 30,
    "Al Riyan": 17,
    "Ibhaar": 18,
    "Roohi Wa Roohak Silver": 20,
    "Ghazlaan": 20,
    "Mibraak": 18,
    "Raniya": 18,
    "Shamookh Silver": 20,
    "Aaliya": 27,
    "Rooh Al Oud": 12,
    "Dehnal Oudh Asal": 3,
    "Dehnal Oud Turaas": 3,
    "Dehnal Oud Azeem": 3,
    "Dehnal Oud Aqdam": 3,
    "Dehnal Oudh Combodi": 3,
    "Mazoon Rose Gold": 18,
    "Mazoon Gold": 18,
    "Al Fursan": 18,
    "Fatima": 15,
    "Dehnal Oud Sheikh Qadim": 3,
    "Dehnal Oud Qaisar Seufi": 3
}
DEHNAL_OILS = {
    "Rooh Al Oud": 12,
    "Dehnal Oudh Asal": 3,
    "Dehnal Oud Turaas": 3,
    "Dehnal Oud Azeem": 3,
    "Dehnal Oud Aqdam": 3,
    "Dehnal Oudh Combodi": 3,
    "Dehnal Oud Sheikh Qadim": 3,
    "Dehnal Oud Qaisar Seufi": 3,
    "Oud Pure Magical Thai": 3
}
DISCOVERY_NAMES = [
    "Aaliya",
    "Al Riyan",
    "Alf Wardat",
    "Amber Pure",
    "Ana Wa Anta",
    "Anabia Blue",
    "Anabia Red",
    "Arabian Treasure",
    "Azaari",
    "Ghazlaan",
    "Haneen Gold",
    "Haneen Rose Gold",
    "Hareem Al Sultan Blue",
    "Hareem Al Sultan Gold",
    "Hareem Al Sultan Silver",
    "Ibhaar",
    "Jameel",
    "Johayna Green",
    "Johayna Purple",
    "Kayaan Gold",
    "Kayaan Silver",
    "Lulu Al Khaleej",
    "Malika Green",
    "Malika Red",
    "Nagham",
    "Oud & Musk",
    "Pink Musk",
    "Pure Musk",
    "Purple Musk",
    "Raniya",
    "Rasha",
    "Rimaal Brown",
    "Roohi Wa Roohak Gold",
    "Safari Gold",
    "Shamookh Gold",
    "Shamookh Silver"
]

class KhadlajPerfumeOilTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = {p["canonical_name"]: p for p in CATALOG["products"] if p.get("brand") == "Khadlaj"}
        cls.variants = CATALOG["variants"]
        cls.families = {f["family_id"]: f for f in REGISTRY["families"] if f.get("brand") == "Khadlaj"}

    def test_official_perfume_oil_collection_has_48_canonical_names_and_sizes(self):
        family = self.families["khadlaj_official_perfume_oils"]
        names = {p["canonical_name"] for p in family["products"]}
        self.assertEqual(len(names), 48)
        self.assertEqual(names, set(OFFICIAL_OILS))
        for name, size in OFFICIAL_OILS.items():
            with self.subTest(name=name):
                product = self.products[name]
                matched = [v for v in self.variants if v.get("product_id") == product["product_id"] and v.get("size_ml") == size]
                self.assertEqual(len(matched), 1)
                self.assertEqual(matched[0].get("concentration"), "Perfume Oil")
                self.assertTrue(matched[0].get("source_evidence_url"))

    def test_dehn_al_oud_range_has_nine_separate_identities_and_confirmed_sizes(self):
        family = self.families["khadlaj_dehn_al_oud"]
        names = {p["canonical_name"] for p in family["products"]}
        self.assertEqual(names, set(DEHNAL_OILS))
        for name, size in DEHNAL_OILS.items():
            with self.subTest(name=name):
                product = self.products[name]
                self.assertEqual(product.get("family_id"), "khadlaj_dehn_al_oud")
                matched = [v for v in self.variants if v.get("product_id") == product["product_id"] and v.get("size_ml") == size]
                self.assertEqual(len(matched), 1)
                self.assertEqual(matched[0].get("concentration"), "Perfume Oil")

    def test_fragrantica_oil_discovery_family_is_separate(self):
        family = self.families["khadlaj_perfume_oils"]
        names = {p["canonical_name"] for p in family["products"]}
        self.assertEqual(len(names), 36)
        self.assertEqual(names, set(DISCOVERY_NAMES))
        self.assertNotEqual(names, set(OFFICIAL_OILS))

if __name__ == "__main__":
    unittest.main()
