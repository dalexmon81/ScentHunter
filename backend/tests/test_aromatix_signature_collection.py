"""Regression tests for the ten Aromatix x French Avenue signature fragrances."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

NAMES = ("Teas Me", "Frostbite", "Naughty Dates", "Sun Kissed", "Forbidden Fruit",
         "Magnetiq", "Platine Blanc", "X Xandal", "Royal Taboo", "Carnal Desire")
SOURCE = "https://shoparomatix.com/pages/aromatic-collection"


class AromatixSignatureCollectionTests(unittest.TestCase):
    def test_all_ten_signature_products_have_official_listing_evidence(self):
        products = {p["canonical_name"]: p for p in CATALOG["products"] if p.get("brand") == "Aromatix"}
        for name in NAMES:
            with self.subTest(product=name):
                p = products[name]
                self.assertEqual(p["source_url"], SOURCE)
                self.assertEqual(p["identity_status"], "source_listed_name")
                self.assertEqual(p["concentration"], "Eau de Parfum")
                self.assertEqual(p["formats_ml"], [100])
                variants = [v for v in CATALOG["variants"] if v["product_id"] == p["product_id"]]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0]["size_ml"], 100)
                self.assertEqual(variants[0]["concentration"], "Eau de Parfum")
                self.assertEqual(variants[0]["source_evidence_url"], SOURCE)

    def test_all_ten_are_in_the_aromatix_family_registry(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "aromatix_catalog")
        names = {p["canonical_name"] for p in family["products"]}
        self.assertTrue(set(NAMES).issubset(names))

    def test_product_and_variant_ids_are_unique(self):
        product_ids = [p["product_id"] for p in CATALOG["products"]]
        variant_ids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))


if __name__ == "__main__":
    unittest.main()
