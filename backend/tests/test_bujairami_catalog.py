"""Regression tests for Bujairami listing evidence and identity handling."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


class BujairamiCatalogTests(unittest.TestCase):
    def test_hectic_official_page_and_100ml_variant_are_verified(self):
        matches = [
            p for p in CATALOG["products"]
            if p.get("brand") == "Bujairami" and p.get("canonical_name") == "Hectic"
        ]
        self.assertEqual(len(matches), 1)
        product = matches[0]
        source = "https://bujairami.ae/products/hectic-inspired-by-louis-vuitton-imagination-extrait"
        self.assertEqual(product["source_url"], source)
        self.assertEqual(product["identity_status"], "source_verified_name")
        self.assertIn(100, product.get("formats_ml", []))
        variants = [
            v for v in CATALOG["variants"]
            if v.get("product_id") == product["product_id"]
        ]
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0].get("size_ml"), 100)
        self.assertEqual(variants[0].get("source_evidence_url"), source)

    def test_hectic_is_in_bujairami_family_registry(self):
        family = next(f for f in REGISTRY["families"] if f["brand"] == "Bujairami")
        self.assertIn("Hectic", {p["canonical_name"] for p in family["products"]})

    def test_hectic_has_no_unverified_concentration_or_commercial_data(self):
        product = next(
            p for p in CATALOG["products"]
            if p.get("brand") == "Bujairami" and p.get("canonical_name") == "Hectic"
        )
        self.assertNotIn("concentration", product)
        self.assertNotIn("gtin", product)
        for field in ("price", "stock", "availability"):
            self.assertNotIn(field, product)

    def test_catalog_product_ids_and_brand_name_pairs_are_unique(self):
        products = CATALOG["products"]
        ids = [p["product_id"] for p in products]
        pairs = [(p.get("brand") or p.get("brand_name"), p.get("canonical_name") or p.get("name")) for p in products]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(pairs), len(set(pairs)))


if __name__ == "__main__":
    unittest.main()
