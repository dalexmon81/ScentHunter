"""Regression tests for the official Games of Spades catalog expansion."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG_PATH = BACKEND / "product_catalog.json"
REGISTRY_PATH = BACKEND / "family_registry.json"

EXPECTED_GAMES_OF_SPADES = [
    "King",
    "Queen",
    "Jack",
    "Ace",
    "Wildcard",
    "All In",
    "Bid",
    "Black Sapphire",
    "Blind Bid",
    "Bluff",
    "Bonus",
    "Boston",
    "Diamond",
    "Double Bonus",
    "Emerald",
    "Full House Refresh",
    "Gold",
    "High Roller",
    "Jackpot",
    "Moon",
    "No Limit",
    "Opal",
    "Platinum",
    "Rouge",
    "Royale",
    "Ruby",
    "Topaz",
    "Trick",
    "Win",
    "Yellow Sapphire"
]


class GamesOfSpadesCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.products = cls.catalog["products"]
        cls.variants = cls.catalog["variants"]

    def test_expected_fragrance_identities_exist_once(self):
        games = [
            p for p in self.products
            if p.get("brand") == "Games of Spades"
        ]
        names = [p["canonical_name"] for p in games]
        self.assertEqual(set(names), set(EXPECTED_GAMES_OF_SPADES))
        self.assertEqual(len(names), len(set(names)))

    def test_product_ids_are_unique(self):
        ids = [p["product_id"] for p in self.products]
        self.assertEqual(len(ids), len(set(ids)))

    def test_brand_and_canonical_name_pairs_are_unique(self):
        keys = [
            (p.get("brand") or p.get("brand_name"), p.get("canonical_name") or p.get("name"))
            for p in self.products
        ]
        self.assertEqual(len(keys), len(set(keys)))

    def test_games_of_spades_family_registry_matches_catalog(self):
        family = next(
            f for f in self.registry["families"]
            if f["family_id"] == "games_of_spades_catalog"
        )
        registry_names = {p["canonical_name"] for p in family["products"]}
        catalog_names = {
            p["canonical_name"] for p in self.products
            if p.get("brand") == "Games of Spades"
        }
        self.assertEqual(registry_names, catalog_names)

    def test_new_game_of_spades_names_have_official_source(self):
        games = [
            p for p in self.products
            if p.get("brand") == "Games of Spades"
        ]
        for product in games:
            with self.subTest(name=product["canonical_name"]):
                self.assertIn("jomilanoparis.com", product.get("source_url", ""))

    def test_no_offers_or_unverified_variant_rows_were_created(self):
        games = {
            p["product_id"] for p in self.products
            if p.get("brand") == "Games of Spades"
        }
        for product in self.products:
            if product["product_id"] in games:
                for field in ("price", "stock", "shipping_cost", "store_url", "availability"):
                    self.assertNotIn(field, product)
        for variant in self.variants:
            if variant.get("product_id") in games:
                self.assertTrue(variant.get("size_ml"))
                self.assertTrue(variant.get("concentration"))


if __name__ == "__main__":
    unittest.main()
