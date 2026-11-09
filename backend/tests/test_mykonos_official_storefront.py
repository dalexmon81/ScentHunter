"""Regression tests for MYKONOS official storefront identity and variant provenance."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
TRAVEL_SIZE_URL = "https://officialmykonos.com/products/mykonos-sansa-edp-travel-size-15ml"
OFFICIAL_PRODUCTS = {
    "Aphrodite": "mykonos-aphrodite-extrait-de-parfum-50ml-100ml",
    "Baby Love": "mykonos-baby-love-edp-50ml",
    "Black Opera": "mykonos-black-opera-extrait-de-parfum-100ml",
    "Bonfire Vanilla": "mykonos-bonfire-vanilla-extrait-de-parfum-50ml",
    "Cafe Drops": "mykonos-cafe-drops-extrait-de-parfum-50ml",
    "California Blue": "mykonos-california-blue-extrait-de-parfum-50ml",
    "California Club": "mykonos-california-club-extrait-de-parfum-50ml",
    "California": "mykonos-california-signature-50ml",
    "Caramel Fudge Cookie": "mykonos-caramel-fudge-cookie-edp-50ml",
    "Coconut Dreams": "mykonos-coconut-dreams-extrait-de-parfum-50ml",
    "Conquer": "mykonos-conquer-extrait-de-parfum-100ml",
    "Constantine": "mykonos-constantine-extrait-de-parfum-50ml",
    "Crimson": "mykonos-crimson-extrait-de-parfum-100ml",
    "Dark Secret": "mykonos-dark-secret-extrait-de-parfum-100ml",
    "Dreamscape": "mykonos-dreamscape-extrait-de-parfum-50ml-100ml",
    "Enchanted": "mykonos-enchanted-extrait-de-parfum-50ml-100ml",
    "Hawaiian Crush": "mykonos-hawaiian-crush-extrait-de-parfum-50ml",
    "Imperium": "mykonos-imperium-extrait-de-parfum-100ml",
    "Inception": "mykonos-inception-extrait-de-parfum-50ml",
    "Inferno": "mykonos-inferno-extrait-de-parfum-100ml",
    "Luminos": "mykonos-luminos-extrait-de-parfum-50ml",
    "Marbella": "mykonos-marbella-extrait-de-parfum-100ml",
    "Matcha Latte": "mykonos-matcha-latte-extrait-de-parfum-50ml",
    "Mayfair": "mykonos-mayfair-extrait-de-parfum-100ml",
    "Milk Drops": "mykonos-milk-drops-extrait-de-parfum-50ml",
    "Monaco Royale": "mykonos-monaco-royale-extrait-de-parfum-50ml-100ml",
    "Moroccan Vanilla": "mykonos-moroccan-vanilla-extrait-de-parfum-100ml",
    "Musk Aura": "mykonos-musk-aura-extrait-de-parfum-100ml",
    "Nautilus": "mykonos-nautilus-extrait-de-parfum-100ml",
    "On The Rocks": "mykonos-on-the-rocks-extrait-de-parfum-100ml",
    "Paradise": "mykonos-paradise-extrait-de-parfum-50ml",
    "Penthouse": "mykonos-penthouse-extrait-de-parfum-100ml",
    "Pink Beach": "mykonos-pink-beach-edp-50ml",
    "Pink Drops": "mykonos-pink-drops-extrait-de-parfum-50ml",
    "Reflection Elixir": "mykonos-reflection-elixir-extrait-de-parfum-50ml",
    "Reflection": "mykonos-reflection-extrait-de-parfum-50ml-100ml",
    "Royal Ispahan": "mykonos-royal-ispahan-extrait-de-parfum-50ml-100ml",
    "Satin Blanc": "mykonos-satin-blanc-extrait-de-parfum-100ml",
    "Senja": "mykonos-senja-edp-50ml",
    "Silent Whisper": "mykonos-silent-whisper-extrait-de-parfum-50ml-100ml",
    "Slow Living": "mykonos-slow-living-edp-50ml",
    "Sorrento": "mykonos-sorrento-extrait-de-parfum-50ml-100ml",
    "Sparkling Rosé": "mykonos-sparkling-rose-extrait-de-parfum-100ml",
    "Stilettos": "mykonos-stilettos-edp-50ml",
    "Untamed": "mykonos-untamed-extrait-de-parfum-100ml",
    "Utopia": "mykonos-utopia-extrait-de-parfum-100ml",
    "Vanilla Clouds": "mykonos-vanilla-clouds-extrait-de-parfum-50ml-1",
    "Verve": "mykonos-verve-extrait-de-parfum-when-in-paris-edp-50ml",
    "Xoxo Rosy": "mykonos-xoxo-rosy-edp-50ml",
    "MyEgo": "mykonos-x-alterego-myego-extrait-de-parfum-50ml-100ml",
    "Empire x RRQ": "mykonos-x-rrq-empire-extrait-de-parfum-50ml-100ml",
    "Glitch": "mykonos-x-setiawanade-glitch-extrait-de-parfum-50ml",
    "Invade": "mykonos-x-setiawanade-invade-extrait-de-parfum-50ml"
}

class MykonosOfficialStorefrontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = {
            p["canonical_name"]: p for p in cls.catalog["products"]
            if p.get("brand_name", p.get("brand")) == "Mykonos"
        }
        cls.variants = cls.catalog.get("variants", [])

    def test_all_current_named_storefront_products_have_individual_evidence(self):
        self.assertEqual(len(OFFICIAL_PRODUCTS), 53)
        for name, slug in OFFICIAL_PRODUCTS.items():
            with self.subTest(name=name):
                self.assertIn(name, self.products)
                product = self.products[name]
                url = f"https://officialmykonos.com/products/{slug}"
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)

    def test_explicit_size_variants_point_to_their_own_product_page(self):
        for name, slug in OFFICIAL_PRODUCTS.items():
            product = self.products[name]
            url = f"https://officialmykonos.com/products/{slug}"
            for variant in self.variants:
                if variant.get("product_id") == product["product_id"] and variant.get("size_ml") != 15:
                    with self.subTest(name=name, size=variant.get("size_ml")):
                        self.assertEqual(variant.get("source_evidence_url"), url)

    def test_shared_15ml_travel_size_options_keep_shared_page_provenance(self):
        allowed = {
            "Dark Secret", "Musk Aura", "Sansa", "Satin Blanc", "Sparkling Rosé",
            "Black Opera", "Moroccan Vanilla", "Affair", "Utopia", "Tea Poetry",
            "Hawaiian Crush", "On The Rocks", "Royal Ispahan", "Crimson",
            "California", "California Blue", "Penthouse", "Monaco Royale",
        }
        rows = [
            p for p in self.products.values()
            if any(v.get("product_id") == p["product_id"] and v.get("size_ml") == 15
                   for v in self.variants)
        ]
        self.assertEqual({p["canonical_name"] for p in rows}, allowed)
        for product in rows:
            matching = [
                v for v in self.variants
                if v.get("product_id") == product["product_id"] and v.get("size_ml") == 15
            ]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0].get("source_evidence_url"), TRAVEL_SIZE_URL)

    def test_unresolved_concentration_is_not_guessed(self):
        product = self.products["Vanilla Clouds"]
        self.assertNotIn("concentration", product)
        variants = [v for v in self.variants if v.get("product_id") == product["product_id"]]
        self.assertEqual(len(variants), 1)
        self.assertNotIn("concentration", variants[0])

    def test_slow_living_concentrations_remain_variant_specific(self):
        product = self.products["Slow Living"]
        variants = {
            v["size_ml"]: v.get("concentration")
            for v in self.variants if v.get("product_id") == product["product_id"]
        }
        self.assertEqual(variants, {50: "Eau de Parfum", 100: "Extrait de Parfum"})

if __name__ == "__main__":
    unittest.main()
