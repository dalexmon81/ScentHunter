"""Regression checks for the Assaf range harvest.

The 140-name independent index is discovery evidence, not official product-page
verification. New records deliberately remain source_listed_name and have no
inferred concentration, size, GTIN, price, stock or retailer offer.
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

    def test_new_harvest_records_remain_listing_backed(self):
        for product in self.products:
            if product["product_id"].startswith("SH-ASSAF-HARVEST-"):
                self.assertEqual(product["identity_status"], "source_listed_name")
                self.assertEqual(product["source_url"], "https://assafperfumes.eu/perfumes/")
                self.assertNotIn("concentration", product)
                self.assertNotIn("formats_ml", product)

if __name__ == "__main__":
    unittest.main()
