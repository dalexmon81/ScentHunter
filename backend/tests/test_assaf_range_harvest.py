"""Regression checks for the Assaf range harvest and official detail upgrades.

The 140-name independent index is discovery evidence; only products with
matching official detail pages are promoted to source_verified_name.
"""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
EXPECTED = [
    "90s",
    "Addict Blue",
    "Alex Enable",
    "Alexandra",
    "Arkle",
    "Arrogate Addict",
    "Arrogate Addict Elixir",
    "Arrogate Bakhur",
    "Arrogate Blue",
    "Arrogate Blue de Elixir",
    "Arrogate Blue Exclusive",
    "Arrogate Colt",
    "Arrogate Comete",
    "Arrogate Euphoria",
    "Arrogate Girl",
    "Arrogate Million Celebration",
    "Arrogate Oud Bakhur",
    "Arrogate Pink",
    "Arrogate Pink Diva",
    "Arrogate Pink Rose",
    "Attacks",
    "Attacks Blue",
    "Attacks X",
    "Aura",
    "Aura 30",
    "Aura Black",
    "Baby Girl",
    "Bakhur Pegasus",
    "Black Lady",
    "Black Wild",
    "Bonjour",
    "Boom Blue",
    "Challenge",
    "Charisma",
    "Charlotte",
    "Copacapana",
    "Crown Spirit",
    "Dangerous Arrogate",
    "Deep Amber",
    "Elizabeth",
    "Error 404",
    "Feeling",
    "First Night",
    "Forever Here",
    "Frankel Afternoon",
    "Frankel Ascot",
    "Frankel Aventus",
    "Frankel Aventus Black Elixir",
    "Frankel Aventus Intense",
    "Frankel Aventus Strike",
    "Frankel Battle",
    "Frankel Beach Afternoon",
    "Frankel Black Elixir",
    "Frankel Blackout",
    "Frankel Blue Elixir",
    "Frankel Chill",
    "Frankel Elysium",
    "Frankel Green Irish",
    "Frankel Imagination",
    "Frankel Silver",
    "Frankel Silver Elixir",
    "Frankel Storm",
    "Garden Rose",
    "Glitch",
    "Greatness",
    "Green Iris",
    "Gris Erik",
    "Gris Flora",
    "Happy Moment",
    "Harmony",
    "Homme Pegasus",
    "Hook Blue",
    "I Am Here",
    "I'm Here Enable",
    "Juliet",
    "King Enable",
    "Lady",
    "Lady Supreme",
    "Legend",
    "Lip Stick",
    "Lord",
    "Martha",
    "Millionaire Enable",
    "Miss Arrogate",
    "Miss Arrogate Diva",
    "Miss Flora",
    "Miss Grace Dance Arrogate",
    "Miss Gris",
    "Miss Gris Dance",
    "Miss Gris Intense",
    "Miss Noble",
    "Miss Sakura",
    "Morning Girl",
    "No Chance",
    "No Comment",
    "Noble",
    "Noble Cavale",
    "Nomad",
    "Onset",
    "Pegasus Oud",
    "Pegasus Reflection",
    "Pink Lady",
    "Pink Queen",
    "Pink Queen Exclusive",
    "Private Purple",
    "Proino Pegasus",
    "Promise",
    "Queen of Seduction",
    "Rebel Enable",
    "Risk Comete",
    "Risk X",
    "Rouge",
    "Rouge Thunder",
    "Ruffian Red",
    "Savage",
    "Search",
    "Sherlock",
    "Shift",
    "Stand By",
    "Strike Black",
    "Swimming in Summer",
    "Swimming In Summer Intense",
    "Take Off",
    "Tobacco Black 40",
    "Tobacco Jam 50",
    "Tobacco Jam 60",
    "Tobacco Pacha",
    "Tobacco Rage 32",
    "Troy Enable",
    "Wanted Lady",
    "Warrior",
    "Wild Colt",
    "Wild Colt Bakhur",
    "Wild Colt Boss",
    "Wild Colt Elixir",
    "Wild Colt Exclusive",
    "Wild Colt Outlast",
    "Wild Colt Smoky",
    "Wild Colt Tobacco",
    "Wild Pegasus"
]

class AssafRangeHarvestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = [p for p in cls.catalog["products"] if p.get("brand") == "Assaf"]
        cls.by_name = {p["canonical_name"].casefold(): p for p in cls.products}

    def test_all_140_indexed_names_are_in_catalog(self):
        for name in EXPECTED:
            with self.subTest(name=name):
                self.assertIn(name.casefold(), self.by_name)

    def test_no_duplicate_assaf_canonical_names(self):
        self.assertEqual(len(self.products), len(self.by_name))

    def test_unverified_harvest_records_remain_listing_backed(self):
        detail_verified = {
            "Arrogate Pink",
            "Arrogate Pink Diva",
            "Dangerous Arrogate",
            "Gris Erik",
            "Miss Arrogate",
            "Rebel Enable",
            "Arrogate Girl",
            "Arrogate Colt",
            "Arrogate Comete",
            "Arrogate Addict Elixir",
            "Arrogate Euphoria",
            "Arrogate Blue de Elixir",
            "Arrogate Blue Exclusive",
        }
        for product in self.products:
            if product["product_id"].startswith("SH-ASSAF-HARVEST-") and product["canonical_name"] not in detail_verified:
                with self.subTest(product=product["canonical_name"]):
                    self.assertEqual(product["identity_status"], "source_listed_name")
                    self.assertEqual(product["source_url"], "https://assafperfumes.eu/perfumes/")
                    if name == "Arrogate Addict Elixir":
                    self.assertEqual(product.get("concentration"), "Eau de Parfum")
                else:
                    self.assertNotIn("concentration", product)
                    self.assertNotIn("formats_ml", product)

    def test_official_detail_pages_upgrade_fourteen_existing_identities(self):
        expected = {
            "Arrogate Pink": ({"200"}, "https://assaf.ae/products/arrogate-pink-200ml"),
            "Arrogate Pink Diva": ({"200"}, "https://assaf.ae/products/arrogate-pink-diva"),
            "Dangerous Arrogate": ({"200"}, "https://assaf.ae/products/dangerous-arrogate-200ml"),
            "Gris Erik": ({"100", "200"}, "https://assaf.ae/products/gris-erik"),
            "Miss Arrogate": ({"200"}, "https://assaf.ae/products/miss-arrogate"),
            "Rebel Enable": ({"150"}, "https://assaf.ae/products/edp-rebel-enable-150ml"),
            "Wild Colt Elixir": ({"200"}, "https://assaf.ae/products/edp-wild-colt-elixer-200ml"),
            "Arrogate Girl": ({"200"}, "https://assaf.ae/products/arrogate-girl"),
            "Arrogate Colt": ({"200"}, "https://assaf.ae/products/arrogate-colt"),
            "Arrogate Comete": ({"200"}, "https://assaf.ae/products/edp-arrogate-comete-200ml-copy"),
            "Arrogate Addict Elixir": ({"150"}, "https://assaf.ae/products/edp-arogate-addict-elixir-150ml"),
            "Arrogate Euphoria": ({"150"}, "https://assaf.ae/products/arrogate-euphoria-150ml"),
            "Arrogate Blue de Elixir": ({"200"}, "https://assaf.ae/products/arrogate-blue-de-elixir-200ml"),
            "Arrogate Blue Exclusive": ({"200"}, "https://assaf.ae/products/arrogate-blue-exclusive"),
        }
        variants = self.catalog["variants"]
        for name, (sizes, source_url) in expected.items():
            with self.subTest(product=name):
                product = self.by_name[name.casefold()]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], source_url)
                actual_sizes = {
                    str(v["size_ml"]) for v in variants
                    if v["product_id"] == product["product_id"]
                }
                self.assertEqual(actual_sizes, sizes)
                self.assertTrue(set(map(int, sizes)).issubset(set(product["formats_ml"])))
                self.assertNotIn("concentration", product)

if __name__ == "__main__":
    unittest.main()
