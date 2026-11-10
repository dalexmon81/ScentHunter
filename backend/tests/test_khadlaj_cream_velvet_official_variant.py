"""Regression coverage for Khadlaj Cream Velvet's official product variant."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

PRODUCT_URL = "https://khadlaj-perfumes.com/products/cream-velvet-100-ml-extrait-de-parfum-for-women-best-perfumes"
GTIN = "6291107978819"


class KhadlajCreamVelvetOfficialVariantTests(unittest.TestCase):
    def test_existing_identity_is_upgraded_without_creating_a_duplicate(self):
        products = [
            p for p in CATALOG["products"]
            if p.get("brand") == "Khadlaj" and p.get("canonical_name") == "Cream Velvet"
        ]
        self.assertEqual(len(products), 1)
        product = products[0]
        self.assertEqual(product["product_id"], "SH-KHADLAJ-142e4d1e")
        self.assertEqual(product["identity_status"], "source_verified_name")
        self.assertEqual(product["source_url"], PRODUCT_URL)
        self.assertEqual(product["source_product_url"], PRODUCT_URL)
        self.assertEqual(product["source_evidence_url"], PRODUCT_URL)
        self.assertEqual(product["concentration"], "Extrait de Parfum")
        self.assertEqual(product["formats_ml"], [100])

    def test_one_variant_matches_official_size_concentration_and_gtin(self):
        product = next(
            p for p in CATALOG["products"]
            if p.get("brand") == "Khadlaj" and p.get("canonical_name") == "Cream Velvet"
        )
        variants = [
            v for v in CATALOG["variants"]
            if v.get("product_id") == product["product_id"]
        ]
        self.assertEqual(len(variants), 1)
        variant = variants[0]
        self.assertEqual(variant["variant_id"], "SHV-SH-KHADLAJ-142e4d1e-100-EXTRAIT")
        self.assertEqual(variant["size_ml"], 100)
        self.assertEqual(variant["concentration"], "Extrait de Parfum")
        self.assertEqual(variant["gtin"], GTIN)
        self.assertEqual(variant["source_url"], PRODUCT_URL)
        self.assertEqual(variant["source_evidence_url"], PRODUCT_URL)

    def test_khadlaj_family_registry_is_aligned(self):
        family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "khadlaj_catalog"
        )
        matches = [
            p for p in family["products"]
            if p.get("canonical_name") == "Cream Velvet"
        ]
        self.assertEqual(len(matches), 1)
        self.assertIn(100, matches[0].get("formats_ml", []))


if __name__ == "__main__":
    unittest.main()
