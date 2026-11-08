"""Regression tests for Maison Asrar Lock & Key products and registry parity."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Plot Twist": ("SH-MAISON-ASRAR-PLOT-TWIST-X002", "SHV-SH-MAISON-ASRAR-PLOT-TWIST-X002-100-EDP", "https://shop-gulforchid.com/products/plot-twist"),
    "Love Key": ("SH-MAISON-ASRAR-LOVE-KEY-X003", "SHV-SH-MAISON-ASRAR-LOVE-KEY-X003-100-EDP", "https://shop-gulforchid.com/products/love-key"),
    "Unsolved Mystery": ("SH-MAISON-ASRAR-UNSOLVED-MYSTERY-X001", "SHV-SH-MAISON-ASRAR-UNSOLVED-MYSTERY-X001-100-EDP", "https://shop-gulforchid.com/products/unsolved-mystery"),
}

class MaisonAsrarLockAndKeyTests(unittest.TestCase):
    def test_official_detail_identity_and_source(self):
        for name, (product_id, _, source) in EXPECTED.items():
            with self.subTest(name=name):
                matches = [p for p in CATALOG["products"] if p.get("brand") == "Maison Asrar" and p.get("canonical_name") == name]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]["product_id"], product_id)
                self.assertEqual(matches[0]["identity_status"], "source_verified_name")
                self.assertEqual(matches[0]["source_url"], source)
                self.assertEqual(matches[0]["family_id"], "maison_asrar_catalog")

    def test_100ml_edp_variants_exist(self):
        for name, (product_id, variant_id, _) in EXPECTED.items():
            with self.subTest(name=name):
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == product_id]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0]["variant_id"], variant_id)
                self.assertEqual(variants[0]["size_ml"], 100)
                self.assertEqual(variants[0]["concentration"], "Eau de Parfum")

    def test_family_registry_matches_all_three(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "maison_asrar_catalog")
        for name in EXPECTED:
            with self.subTest(name=name):
                record = next(p for p in family["products"] if p["canonical_name"] == name)
                self.assertEqual(record["formats_ml"], [100])

    def test_listing_descriptors_are_aliases_not_duplicate_products(self):
        products = [p for p in CATALOG["products"] if p.get("brand") == "Maison Asrar"]
        self.assertFalse(any(p["canonical_name"] in {"Black Grapefruit", "Bloom"} for p in products))
        black = next(p for p in products if p["canonical_name"] == "Black")
        bloom = next(p for p in products if p["canonical_name"] == "Bloom Bloom")
        self.assertIn("Black Grapefruit", black["aliases"])
        self.assertIn("Bloom", bloom["aliases"])

    def test_catalog_ids_and_brand_name_pairs_are_unique(self):
        products = CATALOG["products"]
        ids = [p["product_id"] for p in products]
        pairs = [(p.get("brand") or p.get("brand_name"), p.get("canonical_name") or p.get("name")) for p in products]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(pairs), len(set(pairs)))


if __name__ == "__main__":
    unittest.main()
