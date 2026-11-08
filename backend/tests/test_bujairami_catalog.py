"""Regression tests for the official Bujairami Hectic identity."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


class BujairamiCatalogTests(unittest.TestCase):
    def test_hectic_is_a_canonical_name_with_official_provenance(self):
        matches = [
            p for p in CATALOG["products"]
            if p.get("brand") == "Bujairami" and p.get("canonical_name") == "Hectic"
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(
            matches[0]["source_url"],
            "https://bujairami.com.au/products/hectic-inspired-by-louis-vuitton-imagination-extrait",
        )
        self.assertEqual(matches[0]["identity_status"], "source_verified_name")

    def test_hectic_is_in_bujairami_family_registry(self):
        family = next(f for f in REGISTRY["families"] if f["brand"] == "Bujairami")
        self.assertIn("Hectic", {p["canonical_name"] for p in family["products"]})

    def test_no_concentration_size_or_gtin_was_inferred(self):
        product = next(
            p for p in CATALOG["products"]
            if p.get("brand") == "Bujairami" and p.get("canonical_name") == "Hectic"
        )
        for field in ("concentration", "size_ml", "gtin", "price", "stock", "availability"):
            self.assertNotIn(field, product)

    def test_catalog_product_ids_and_brand_name_pairs_are_unique(self):
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
