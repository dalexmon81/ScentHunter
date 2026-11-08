"""Regression tests for Arabiyat Prestige Mahd Al Dhahab Extrait."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

BRAND = "Arabiyat Prestige"
NAME = "Mahd Al Dhahab Extrait"
SOURCE = "https://eu.myperfumes.ae/en-de/products/mahd-al-dhahab-extrait"


class ArabiyatPrestigeExtraitTests(unittest.TestCase):
    def test_extrait_is_a_distinct_canonical_identity(self):
        matches = [
            p for p in CATALOG["products"]
            if p.get("brand") == BRAND and p.get("canonical_name") == NAME
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["source_url"], SOURCE)
        self.assertEqual(matches[0]["identity_status"], "source_verified_name")

    def test_explicit_60ml_extrait_variant_exists(self):
        product = next(
            p for p in CATALOG["products"]
            if p.get("brand") == BRAND and p.get("canonical_name") == NAME
        )
        variants = [v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]]
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0]["size_ml"], 60)
        self.assertEqual(variants[0]["concentration"], "Extrait de Parfum")

    def test_family_registry_contains_distinct_identity_and_format(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "arabiyat_prestige_catalog")
        record = next(p for p in family["products"] if p["canonical_name"] == NAME)
        self.assertEqual(record["formats_ml"], [60])

    def test_product_ids_and_brand_name_pairs_are_unique(self):
        products = CATALOG["products"]
        ids = [p["product_id"] for p in products]
        pairs = [
            (p.get("brand") or p.get("brand_name"), p.get("canonical_name") or p.get("name"))
            for p in products
        ]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(pairs), len(set(pairs)))


if __name__ == "__main__":
    unittest.main()
