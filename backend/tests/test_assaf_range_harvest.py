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
            "Addict Blue",
            "Arrogate Addict",
            "Arrogate Pink Rose",
            "Attacks",
            "First Night",
            "Noble",
            "I'm Here Enable",
            "Frankel Imagination",
            "Strike Black",
            "Troy Enable",
            "Frankel Blue Elixir",
            "Lip Stick",
        }
        for product in self.products:
            if product["product_id"].startswith("SH-ASSAF-HARVEST-") and product["canonical_name"] not in detail_verified:
                with self.subTest(product=product["canonical_name"]):
                    self.assertEqual(product["identity_status"], "source_listed_name")
                    self.assertEqual(product["source_url"], "https://assafperfumes.eu/perfumes/")
                    self.assertNotIn("concentration", product)
                    self.assertNotIn("formats_ml", product)

    def test_official_detail_pages_upgrade_seventeen_existing_identities(self):
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
            "Addict Blue": ({"125"}, "https://assaf.ae/products/addict-blue"),
            "Arrogate Addict": ({"200"}, "https://assaf.ae/products/arrogate-addict-200ml"),
            "Arrogate Pink Rose": ({"150"}, "https://assaf.ae/products/arrogate-pink-rose"),
            "Attacks": ({"125"}, "https://assaf.ae/products/attacks"),
            "First Night": ({"150"}, "https://assaf.ae/products/first-night-1"),
            "Noble": ({"200"}, "https://assaf.ae/products/noble-2"),
            "I'm Here Enable": ({"150"}, "https://assaf.ae/products/edp-im-here-enable-150ml"),
            "Frankel Imagination": ({"200"}, "https://assaf.ae/products/frankel-imagination-200"),
            "Strike Black": ({"125"}, "https://assaf.ae/products/strike-black"),
            "Troy Enable": ({"100"}, "https://assaf.ae/products/troy-enable"),
            "Frankel Blue Elixir": ({"200"}, "https://assaf.ae/products/edp-frankel-blue-elixir-200ml"),
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
                if name == "Arrogate Addict Elixir":
                    self.assertEqual(product.get("concentration"), "Eau de Parfum")
                else:
                    self.assertNotIn("concentration", product)


    def test_lip_stick_official_identity_is_verified_but_conflicting_size_is_not_normalized(self):
        product = self.by_name["lip stick"]
        self.assertEqual(product.get("identity_status"), "source_verified_name")
        self.assertEqual(product.get("source_url"), "https://assaf.ae/products/lip-stick-125ml")
        self.assertNotIn("formats_ml", product)
        self.assertFalse(
            any(variant.get("product_id") == product["product_id"] for variant in self.catalog["variants"])
        )

    def test_two_more_assaf_official_detail_pages_have_supported_variants(self):
        expected = {
            "Frankel Blue Elixir": ("https://assaf.ae/products/edp-frankel-blue-elixir-200ml", 200, "Men"),
            "Strike Black": ("https://assaf.ae/products/strike-black", 125, "Men"),
        }
        for name, (source, size, gender) in expected.items():
            with self.subTest(product=name):
                product = self.by_name[name.casefold()]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), source)
                self.assertEqual(product.get("source_evidence_url"), source)
                self.assertEqual(product.get("formats_ml"), [size])
                self.assertEqual(product.get("gender"), gender)
                matches = [
                    v for v in self.catalog["variants"]
                    if v.get("product_id") == product["product_id"]
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].get("size_ml"), size)
                self.assertEqual(matches[0].get("source_url"), source)
                self.assertEqual(matches[0].get("source_evidence_url"), source)


if __name__ == "__main__":
    unittest.main()
