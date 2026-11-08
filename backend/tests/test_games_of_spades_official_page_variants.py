"""Regression tests for Jo Milano Paris official Game of Spades pages and variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

PAGES = {
    "King": "game-of-spades-king",
    "Queen": "game-of-spades-queen",
    "Wildcard": "game-of-spades-wildcard",
    "All In": "game-of-spades-all-in",
    "Bid": "game-of-spades-bid",
    "Black Sapphire": "game-of-spades-black-sapphire",
    "Blind Bid": "game-of-spades-blind-bid",
    "Bluff": "game-of-spades-bluff-3-4-oz-parfum-spray-unisex",
    "Bonus": "game-of-spades-bonus",
    "Boston": "game-of-spades-boston",
    "Diamond": "game-of-spades-diamond",
    "Double Bonus": "game-of-spades-double-bonus",
    "Emerald": "game-of-spades-emerald",
    "Full House Refresh": "game-of-spades-full-house-refresh-3-4-oz-parfum-spray-unisex",
    "Gold": "game-of-spades-gold",
    "High Roller": "game-of-spades-high-roller-3-4-oz-parfum-spray",
    "Jackpot": "game-of-spades-jackpot",
    "Moon": "game-of-spades-moon",
    "No Limit": "game-of-spades-no-limit",
    "Opal": "game-of-spades-opal",
    "Platinum": "game-of-spades-platinum",
    "Rouge": "game-of-spades-rouge",
    "Royale": "game-of-spades-royale",
    "Ruby": "game-of-spades-ruby",
    "Topaz": "game-of-spades-no-limit-copy",
    "Trick": "game-of-spades-trick-3-4-oz-parfum-spray-unisex",
    "Win": "game-of-spades-win",
    "Yellow Sapphire": "game-of-spades-sapphire",
    "Blue Sapphire": "game-of-spades-blue-sapphire-parfum-spray-3-0-oz-90ml",
}

EXPECTED_VARIANTS = {
    "All In": {(10, "Parfum"), (30, "Parfum"), (50, "Parfum"), (100, "Parfum")},
    "Bid": {(100, "Parfum")},
    "Black Sapphire": {(10, "Parfum"), (30, "Parfum"), (90, "Parfum")},
    "Blind Bid": {(100, "Parfum")},
    "Bluff": {(100, "Extrait de Parfum")},
    "Boston": {(30, "Parfum"), (100, "Parfum")},
    "Diamond": {(10, "Parfum"), (30, "Parfum"), (100, "Parfum")},
    "Double Bonus": {(10, "Parfum"), (30, "Parfum"), (100, "Parfum")},
    "Emerald": {(10, "Extrait de Parfum"), (50, "Extrait de Parfum"), (90, "Extrait de Parfum")},
    "Full House Refresh": {(100, "Parfum")},
    "Gold": {(10, "Parfum"), (30, "Parfum"), (90, "Parfum")},
    "High Roller": {(100, "Parfum")},
    "Jackpot": {(10, "Parfum"), (30, "Parfum"), (100, "Parfum")},
    "King": {(10, "Parfum"), (30, "Parfum"), (100, "Parfum")},
    "Queen": {(100, "Parfum")},
    "Rouge": {(10, "Extrait de Parfum"), (30, "Extrait de Parfum"), (100, "Extrait de Parfum"), (30, "Parfum"), (100, "Parfum")},
    "Ruby": {(100, "Parfum")},
    "Trick": {(100, "Parfum")},
    "Wildcard": {(30, "Parfum"), (50, "Parfum"), (100, "Parfum"), (200, "Parfum")},
    "Win": {(100, "Parfum")},
    "Yellow Sapphire": {(30, "Parfum"), (90, "Parfum")},
    "Blue Sapphire": {(30, "Parfum"), (90, "Parfum")},
}

EXTRAIT_URLS = {
    "Emerald": "https://jomilanoparis.com/products/game-of-spades-emerald-extrait",
    "Rouge": "https://jomilanoparis.com/products/game-of-spades-rouge-extrait",
}


class GamesOfSpadesOfficialPageVariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = {
            p["canonical_name"]: p
            for p in CATALOG["products"]
            if p.get("brand") == "Games of Spades"
        }
        cls.variants = [
            v for v in CATALOG["variants"]
            if v.get("product_id") in {p["product_id"] for p in cls.products.values()}
        ]
        cls.family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "games_of_spades_catalog"
        )

    def test_existing_and_new_products_have_official_individual_pages(self):
        for name, slug in PAGES.items():
            with self.subTest(product=name):
                product = self.products[name]
                url = f"https://jomilanoparis.com/products/{slug}"
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_evidence_url"], url)

    def test_ace_remains_unverified_as_a_distinct_sku(self):
        ace = self.products["Ace"]
        self.assertEqual(ace["identity_status"], "source_listed_name")
        self.assertEqual(
            ace["source_url"],
            "https://jomilanoparis.com/products/game-of-spades-platinum",
        )
        # The official Platinum page mentions Ace, but does not establish a separate Ace product page.

    def test_all_explicit_variants_match_official_sizes_and_concentrations(self):
        for name, expected in EXPECTED_VARIANTS.items():
            with self.subTest(product=name):
                product = self.products[name]
                actual = {
                    (v["size_ml"], v["concentration"])
                    for v in self.variants
                    if v.get("product_id") == product["product_id"]
                }
                self.assertEqual(actual, expected)
                self.assertEqual(
                    product["formats_ml"],
                    sorted({size for size, _concentration in expected}),
                )

    def test_extrait_variants_use_their_own_official_detail_pages(self):
        for name, url in EXTRAIT_URLS.items():
            with self.subTest(product=name):
                product = self.products[name]
                extrait = [
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                    and v.get("concentration") == "Extrait de Parfum"
                ]
                self.assertTrue(extrait)
                self.assertTrue(all(v["source_url"] == url for v in extrait))

    def test_family_registry_formats_match_catalog_formats(self):
        family_products = {
            p["canonical_name"]: p for p in self.family["products"]
        }
        for name, expected in EXPECTED_VARIANTS.items():
            with self.subTest(product=name):
                self.assertEqual(
                    family_products[name]["formats_ml"],
                    sorted({size for size, _concentration in expected}),
                )
        self.assertIn("Blue Sapphire", family_products)

    def test_variant_ids_are_unique_and_parent_products_exist(self):
        ids = [v["variant_id"] for v in self.variants]
        product_ids = {p["product_id"] for p in self.products.values()}
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(v["product_id"] in product_ids for v in self.variants))
        self.assertTrue(all(v.get("size_ml") and v.get("concentration") for v in self.variants))


if __name__ == "__main__":
    unittest.main()
