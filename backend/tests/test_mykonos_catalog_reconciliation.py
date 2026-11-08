"""Mykonos catalog reconciliation regression tests."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
EXPECTED_NAMES = {
    "Adelina", "Affair", "Aphrodite", "Avra Kehdabra", "Baby Love",
    "Berry Caramel Pancake", "Black Opera", "Blaze", "Bloody Mary", "Blossom",
    "Bonfire Vanilla", "Cafe Drops", "Café Lyon", "California", "California Blue",
    "California Club", "Caramel Fudge Cookie", "Celestial", "Chai Crema Latte",
    "Coconut Dreams", "Conquer", "Constantine", "Crimson", "Crystals", "Dark Secret",
    "Daydream", "Déjà Vu", "Dolce Cherry", "Down to Earth", "Dreamscape", "Eclipse",
    "Elysian", "Empire x RRQ", "Enchanted", "Forever Musc", "Glitch",
    "Hawaiian Crush", "Imperium", "Inception", "Inception Reimagined", "Inferno",
    "Inspire Perfume", "Invade", "It's Not Ella", "Ivory", "Jynx", "Kingsman",
    "Luminos", "Marbella", "Matcha Latte", "Mayfair", "Memoir of Meri", "Milk Drops",
    "Monaco Royale", "Monaco Royale Black", "Moroccan Vanilla", "Musk Aura", "MyEgo",
    "Nashi Pear Garden", "Nautilus", "On The Rocks", "Once Upon Don", "Only You",
    "Pandan Sticky Rice", "Paradise", "Penthouse", "Pink Beach", "Pink Drops",
    "Pistachio Cream Cake", "President", "Reflection", "Reflection Elixir", "Rouge",
    "Roulette", "Royal Ispahan", "Sansa", "Satin Blanc", "Senja", "Seven Roses",
    "Shades Perfume", "Shape Shift", "Silent Whisper", "Slow Living",
    "Soft Hour x NCT Haechan", "Sorrento", "Sparkling Rosé", "Stilettos",
    "Tea Poetry", "Undercover", "Untamed", "Utopia", "Vanilla Clouds", "Verve",
    "Violette", "Wallflower", "When in Paris", "Xoxo Rosy", "Zeus", "Zora",
}
TRAVEL_15ML = {
    "Dark Secret", "Musk Aura", "Sansa", "Satin Blanc", "Sparkling Rosé",
    "Black Opera", "Moroccan Vanilla", "Affair", "Utopia", "Tea Poetry",
    "Hawaiian Crush", "On The Rocks", "Royal Ispahan", "Crimson", "California",
    "California Blue", "Penthouse", "Monaco Royale",
}
TRAVEL_SOURCE = "https://officialmykonos.com/products/mykonos-sansa-edp-travel-size-15ml"

class MykonosCatalogReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = [p for p in CATALOG["products"] if p.get("brand") == "Mykonos"]
        cls.product_by_name = {p.get("canonical_name") or p.get("name"): p for p in cls.products}
        cls.product_ids = {p["product_id"] for p in cls.products}
        cls.variants = [v for v in CATALOG["variants"] if v.get("product_id") in cls.product_ids]

    def test_expected_99_canonical_fragrance_identities_are_present(self):
        self.assertEqual(set(self.product_by_name), EXPECTED_NAMES)
        self.assertEqual(len(self.products), 99)

    def test_every_identity_has_source_and_valid_status(self):
        allowed = {"source_verified_name", "source_listed_name"}
        for product in self.products:
            with self.subTest(product=product.get("name")):
                self.assertTrue(product.get("source_url"))
                self.assertIn(product.get("identity_status"), allowed)

    def test_variants_are_unique_and_attached_to_known_products(self):
        variant_ids = [v["variant_id"] for v in self.variants]
        self.assertEqual(len(self.variants), 102)
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertTrue(all(v["product_id"] in self.product_ids for v in self.variants))

    def test_all_variants_have_size_evidence_and_match_product_formats(self):
        for variant in self.variants:
            product = next(p for p in self.products if p["product_id"] == variant["product_id"])
            with self.subTest(product=product.get("name"), size=variant.get("size_ml")):
                self.assertTrue(variant.get("source_evidence_url"))
                self.assertIn(variant["size_ml"], product.get("formats_ml", []))

    def test_official_15ml_travel_size_has_all_18_listed_options(self):
        by_name = {name: product for name, product in self.product_by_name.items()}
        for name in TRAVEL_15ML:
            product = by_name[name]
            matching = [v for v in self.variants if v["product_id"] == product["product_id"] and v["size_ml"] == 15]
            with self.subTest(product=name):
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0].get("source_evidence_url"), TRAVEL_SOURCE)
                self.assertIn(15, product.get("formats_ml", []))

    def test_imperium_is_distinct_from_empire_x_rrq(self):
        self.assertNotEqual(
            self.product_by_name["Imperium"]["product_id"],
            self.product_by_name["Empire x RRQ"]["product_id"],
        )

if __name__ == "__main__":
    unittest.main()
