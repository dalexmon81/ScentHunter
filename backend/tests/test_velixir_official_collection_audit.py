"""Regression audit for Velixir's official perfume collections.

The official EDP collection contains 25 listings including the JTC Bundle;
the official Extrait collection contains 5 listings including Sacred Four
Bundle. Bundles are not canonical fragrance identities.
"""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))

EXPECTED_EDP = {
    "Adonis", "Aphrodite", "Apollo", "Ares", "Artemis", "Asteria",
    "Athena", "Concordia", "Demeter", "Galatea", "Harmonia", "Helios",
    "Hera", "Himeros", "Icarus", "Morpheus", "Narcisus", "Nyx",
    "Orion", "Paladin", "Persephone", "Poseidon", "Selene", "Uranus",
}
EXPECTED_EXTRAIT = {"Comus", "Ether", "Orpheus", "Panacea"}


class VelixirOfficialCollectionAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = [
            row for row in CATALOG["products"]
            if (row.get("brand") or row.get("brand_name")) == "Velixir"
        ]

    def test_official_perfume_identities_match_the_two_collections(self):
        actual_edp = {
            row["canonical_name"] for row in self.products
            if row.get("concentration") == "Eau de Parfum"
        }
        actual_extrait = {
            row["canonical_name"] for row in self.products
            if row.get("concentration") == "Extrait de Parfum"
        }
        self.assertEqual(actual_edp, EXPECTED_EDP)
        self.assertEqual(actual_extrait, EXPECTED_EXTRAIT)
        self.assertEqual(len(self.products), 28)

    def test_collection_bundles_are_not_canonical_perfume_identities(self):
        names = {row["canonical_name"].casefold() for row in self.products}
        self.assertNotIn("jtc bundle", names)
        self.assertNotIn("sacred four bundle", names)

    def test_velixir_product_ids_are_unique(self):
        ids = [row["product_id"] for row in self.products]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
