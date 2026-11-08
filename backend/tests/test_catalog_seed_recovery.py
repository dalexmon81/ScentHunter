"""Regression checks for the recovered and reconciled canonical seed."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


class CatalogSeedRecoveryTests(unittest.TestCase):
    def test_canonical_catalog_is_non_empty_and_has_unique_identities(self):
        products = CATALOG["products"]
        self.assertGreater(len(products), 1600)
        ids = [p["product_id"] for p in products]
        keys = [(p.get("brand") or p.get("brand_name"), p["canonical_name"]) for p in products]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(keys), len(set(keys)))

    def test_variants_are_unique_and_attached_to_known_products(self):
        product_ids = {p["product_id"] for p in CATALOG["products"]}
        variants = CATALOG["variants"]
        variant_ids = [v["variant_id"] for v in variants]
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertTrue(all(v["product_id"] in product_ids for v in variants))

    def test_games_of_spades_official_identities_are_complete(self):
        expected = {
            "King", "Queen", "Ace", "Wildcard", "All In", "Bid", "Black Sapphire",
            "Blind Bid", "Bluff", "Bonus", "Boston", "Diamond", "Double Bonus",
            "Emerald", "Full House Refresh", "Gold", "High Roller", "Jackpot", "Moon",
            "No Limit", "Opal", "Platinum", "Rouge", "Royale", "Ruby", "Topaz",
            "Trick", "Win", "Yellow Sapphire",
        }
        products = [p for p in CATALOG["products"] if p.get("brand") == "Games of Spades"]
        self.assertEqual({p["canonical_name"] for p in products}, expected)
        self.assertTrue(all("jomilanoparis.com" in p.get("source_url", "") for p in products))

    def test_mykonos_collaboration_names_are_aliases_not_duplicate_identities(self):
        aliases = [
            ("MyEgo", "MyEgo (Mykonos x AlterEgo)"),
            ("Empire x RRQ", "Empire (Mykonos x RRQ)"),
            ("Glitch", "Glitch (Mykonos x SetiawanAde)"),
            ("Invade", "Invade (Mykonos x SetiawanAde)"),
        ]
        products = [p for p in CATALOG["products"] if p.get("brand") == "Mykonos"]
        for canonical, alias in aliases:
            matches = [p for p in products if p["canonical_name"] == canonical]
            self.assertEqual(len(matches), 1)
            self.assertIn(alias, matches[0].get("aliases", []))

    def test_no_retailer_offers_or_prices_are_seeded(self):
        for product in CATALOG["products"]:
            for field in ("price", "stock", "availability", "shipping_cost", "store_url"):
                self.assertNotIn(field, product)


if __name__ == "__main__":
    unittest.main()
