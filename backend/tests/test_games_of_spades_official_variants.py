"""Official Jo Milano Paris Game of Spades catalog and size-variant coverage."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

OFFICIAL_PAGES = {
    "All In": "https://jomilanoparis.com/products/game-of-spades-all-in",
    "Bid": "https://jomilanoparis.com/products/game-of-spades-bid",
    "Black Sapphire": "https://jomilanoparis.com/products/game-of-spades-black-sapphire",
    "Blind Bid": "https://jomilanoparis.com/products/game-of-spades-blind-bid",
    "Bluff": "https://jomilanoparis.com/products/game-of-spades-bluff-3-4-oz-parfum-spray-unisex",
    "Bonus": "https://jomilanoparis.com/products/game-of-spades-bonus",
    "Boston": "https://jomilanoparis.com/products/game-of-spades-boston",
    "Diamond": "https://jomilanoparis.com/products/game-of-spades-diamond",
    "Double Bonus": "https://jomilanoparis.com/products/game-of-spades-double-bonus",
    "Emerald": "https://jomilanoparis.com/products/game-of-spades-emerald",
    "Full House Refresh": "https://jomilanoparis.com/products/game-of-spades-full-house-refresh-3-4-oz-parfum-spray-unisex",
    "Gold": "https://jomilanoparis.com/products/game-of-spades-gold",
    "High Roller": "https://jomilanoparis.com/products/game-of-spades-high-roller-3-4-oz-parfum-spray",
    "Jackpot": "https://jomilanoparis.com/products/game-of-spades-jackpot",
    "King": "https://jomilanoparis.com/products/game-of-spades-king",
    "Queen": "https://jomilanoparis.com/products/game-of-spades-queen",
    "Moon": "https://jomilanoparis.com/products/game-of-spades-moon",
    "No Limit": "https://jomilanoparis.com/products/game-of-spades-no-limit",
    "Opal": "https://jomilanoparis.com/products/game-of-spades-opal",
    "Platinum": "https://jomilanoparis.com/products/game-of-spades-platinum",
    "Rouge": "https://jomilanoparis.com/products/game-of-spades-rouge",
    "Royale": "https://jomilanoparis.com/products/game-of-spades-royale",
    "Ruby": "https://jomilanoparis.com/products/game-of-spades-ruby",
    "Topaz": "https://jomilanoparis.com/products/game-of-spades-no-limit-copy",
    "Trick": "https://jomilanoparis.com/products/game-of-spades-trick-3-4-oz-parfum-spray-unisex",
    "Wildcard": "https://jomilanoparis.com/products/game-of-spades-wildcard",
    "Win": "https://jomilanoparis.com/products/game-of-spades-win",
    "Yellow Sapphire": "https://jomilanoparis.com/products/game-of-spades-sapphire",
    "Blue Sapphire": "https://jomilanoparis.com/products/game-of-spades-blue-sapphire-parfum-spray-3-0-oz-90ml",
    "Emerald Extrait": "https://jomilanoparis.com/products/game-of-spades-emerald-extrait",
    "Rouge Extrait": "https://jomilanoparis.com/products/game-of-spades-rouge-extrait",
}

EXPECTED_VARIANTS = {
    "All In": ([10, 30, 50, 100], None),
    "Black Sapphire": ([10, 30, 90], None),
    "Blind Bid": ([100], "Parfum"),
    "Bonus": ([10, 30, 100], None),
    "Diamond": ([10, 30, 100], "Parfum"),
    "Double Bonus": ([10, 30, 100], None),
    "Emerald": ([30, 100], None),
    "Gold": ([10, 30, 90], "Parfum"),
    "Jackpot": ([10, 30, 100], "Parfum"),
    "King": ([10, 30, 100], "Parfum"),
    "No Limit": ([100], None),
    "Opal": ([100], None),
    "Queen": ([10, 30, 100], "Parfum"),
    "Rouge": ([30, 100], "Parfum"),
    "Royale": ([30, 50, 100], None),
    "Blue Sapphire": ([90], "Parfum"),
    "Emerald Extrait": ([10, 50, 90], "Extrait de Parfum"),
    "Rouge Extrait": ([10, 30, 100], "Extrait de Parfum"),
}


class GamesOfSpadesOfficialVariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = {
            p["canonical_name"]: p
            for p in CATALOG["products"]
            if p.get("brand_name") == "Games of Spades"
        }
        cls.variants = [
            v for v in CATALOG["variants"]
            if v.get("product_id") in {
                p["product_id"] for p in cls.products.values()
            }
        ]
        cls.family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "games_of_spades_catalog"
        )
        cls.registry_products = {
            p["canonical_name"]: p for p in cls.family["products"]
        }

    def test_existing_and_new_products_use_individual_official_pages(self):
        for name, url in OFFICIAL_PAGES.items():
            with self.subTest(product=name):
                product = self.products[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_evidence_url"], url)

    def test_exactly_supported_size_variants_are_present(self):
        for name, (sizes, concentration) in EXPECTED_VARIANTS.items():
            with self.subTest(product=name):
                product = self.products[name]
                self.assertEqual(product["formats_ml"], sizes)
                if concentration:
                    self.assertEqual(product["concentration"], concentration)
                matches = [
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                ]
                self.assertEqual(sorted(v["size_ml"] for v in matches), sizes)
                for variant in matches:
                    self.assertEqual(variant["source_url"], product["source_url"])
                    if concentration:
                        self.assertEqual(variant["concentration"], concentration)

    def test_new_formulation_identities_are_separate_from_originals(self):
        self.assertNotEqual(
            self.products["Emerald"]["product_id"],
            self.products["Emerald Extrait"]["product_id"],
        )
        self.assertNotEqual(
            self.products["Rouge"]["product_id"],
            self.products["Rouge Extrait"]["product_id"],
        )
        self.assertNotEqual(
            self.products["Black Sapphire"]["product_id"],
            self.products["Blue Sapphire"]["product_id"],
        )

    def test_ace_legacy_identity_is_not_falsely_verified(self):
        ace = self.products["Ace"]
        self.assertEqual(ace["identity_status"], "source_listed_name")
        self.assertEqual(ace["source_url"], "https://jomilanoparis.com/collections/all")
        self.assertFalse(any(v["product_id"] == ace["product_id"] for v in self.variants))

    def test_family_registry_and_global_ids_remain_consistent(self):
        for name, (sizes, _concentration) in EXPECTED_VARIANTS.items():
            with self.subTest(product=name):
                self.assertEqual(
                    self.registry_products[name].get("formats_ml"),
                    sizes,
                )
        product_ids = [p["product_id"] for p in CATALOG["products"]]
        variant_ids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        known_products = set(product_ids)
        self.assertTrue(all(v["product_id"] in known_products for v in CATALOG["variants"]))


if __name__ == "__main__":
    unittest.main()
