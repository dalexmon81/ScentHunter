"""Regression tests for Khadlaj perfume-oil products and variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Anabia Red": 20, "Anabia Blue": 20, "Johayna Purple": 20, "Johayna Green": 20,
    "Oud & Musk": 20, "Pure Musk": 20, "Kayaan Silver": 20, "Malika Green": 20,
    "Malika Red": 20, "Purple Musk": 20, "Pink Musk": 20, "Hareem Al Sultan Blue": 35,
    "Kayaan Gold": 20, "Hareem Al Sultan Gold": 35, "Hareem Al Sultan Silver": 35,
    "Jameel": 25, "Haneen Rose Gold": 20, "Roohi Wa Roohak Gold": 20,
    "Haneen Gold": 20, "Alf Wardat": 30, "Al Riyan": 17,
}

class KhadlajPerfumeOilTests(unittest.TestCase):
    def test_official_oil_products_have_exact_sizes_and_type(self):
        products = {p["canonical_name"]: p for p in CATALOG["products"] if p.get("brand") == "Khadlaj"}
        variants = CATALOG["variants"]
        self.assertEqual(sum(1 for p in products.values() if p.get("family_id") == "khadlaj_perfume_oils"), 20)
        for name, size in EXPECTED.items():
            with self.subTest(name=name):
                product = products[name]
                matched = [v for v in variants if v.get("product_id") == product["product_id"] and v.get("size_ml") == size]
                self.assertEqual(len(matched), 1)
                self.assertEqual(matched[0].get("concentration"), "Perfume Oil")
        self.assertEqual(sorted(v["size_ml"] for v in variants if v.get("product_id") == products["Hareem Al Sultan"]["product_id"]), [75])
        self.assertEqual(next(v for v in variants if v.get("product_id") == products["Hareem Al Sultan"]["product_id"])["concentration"], "Eau de Parfum")

    def test_fragrantica_oil_discovery_family_is_separate(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "khadlaj_perfume_oils")
        names = {p["canonical_name"] for p in family["products"]}
        self.assertEqual(len(names), 36)
        for name in ["Aaliya", "Amber Pure", "Arabian Treasure", "Shamookh Gold", "Shamookh Silver"]:
            self.assertIn(name, names)

if __name__ == "__main__":
    unittest.main()
