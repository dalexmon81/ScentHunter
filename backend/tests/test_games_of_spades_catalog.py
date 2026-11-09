"""Regression tests for official Games of Spades catalog coverage."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "King", "Queen", "Ace", "Wildcard", "All In", "Bid", "Black Sapphire",
    "Blind Bid", "Bluff", "Bonus", "Boston", "Diamond", "Double Bonus",
    "Emerald", "Full House Refresh", "Gold", "High Roller", "Jackpot", "Moon",
    "No Limit", "Opal", "Platinum", "Rouge", "Royale", "Ruby", "Topaz", "Trick",
    "Win", "Yellow Sapphire", "Blue Sapphire", "Emerald Extrait", "Rouge Extrait",
}


class GamesOfSpadesCatalogTests(unittest.TestCase):
    def test_expected_fragrance_identities_exist_once(self):
        games = [p for p in CATALOG["products"] if p.get("brand") == "Games of Spades"]
        names = [p["canonical_name"] for p in games]
        self.assertEqual(set(names), EXPECTED)
        self.assertEqual(len(names), len(set(names)))

    def test_product_ids_and_brand_name_pairs_are_unique(self):
        ids = [p["product_id"] for p in CATALOG["products"]]
        pairs = [(p.get("brand") or p.get("brand_name"), p.get("canonical_name") or p.get("name")) for p in CATALOG["products"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_family_registry_covers_all_games(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "games_of_spades_catalog")
        registry_names = {p["canonical_name"] for p in family["products"]}
        catalog_names = {p["canonical_name"] for p in CATALOG["products"] if p.get("brand") == "Games of Spades"}
        self.assertTrue(catalog_names.issubset(registry_names))

    def test_official_provenance_is_not_falsely_assigned_to_ace(self):
        games = {p["canonical_name"]: p for p in CATALOG["products"] if p.get("brand") == "Games of Spades"}
        for name, product in games.items():
            with self.subTest(name=name):
                if name == "Ace":
                    self.assertEqual(product["identity_status"], "source_listed_name")
                    self.assertIn("jhonyusa.com", product["source_url"])
                else:
                    self.assertEqual(product["identity_status"], "source_verified_name")
                    self.assertIn("jomilanoparis.com/products/", product["source_url"])

    def test_new_standalone_products_have_only_explicit_variants(self):
        expected = {
            "Blue Sapphire": ({90, 30}, "Parfum"),
            "Emerald Extrait": ({90, 50, 10}, "Extrait de Parfum"),
            "Rouge Extrait": ({100, 30, 10}, "Extrait de Parfum"),
        }
        for name, (sizes, concentration) in expected.items():
            product = next(p for p in CATALOG["products"] if p.get("brand") == "Games of Spades" and p.get("canonical_name") == name)
            variants = [v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]]
            self.assertEqual({v["size_ml"] for v in variants}, sizes)
            self.assertTrue(all(v["concentration"] == concentration for v in variants))


if __name__ == "__main__":
    unittest.main()
