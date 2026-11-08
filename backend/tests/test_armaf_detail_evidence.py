"""Regression checks for official ARMAF detail-page evidence and sizes."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Club de Nuit Untold": ("Eau de Parfum", {200, 105, 30, 10}),
    "Club de Nuit Intense Man Pure Parfum": ("Parfum", set()),
    "Club de Nuit Sillage": ("Eau de Parfum", {105, 30, 10, 250}),
    "Club de Nuit Woman": ("Eau de Parfum", {200, 105, 30, 250, 10}),
    "Club de Nuit Urban Man Elixir": ("Eau de Parfum", {105, 30, 10, 250}),
    "Club de Nuit Iconic": ("Eau de Parfum", {200, 105, 30, 10}),
}


class ArmafDetailEvidenceTests(unittest.TestCase):
    def test_selected_armaf_identities_have_official_detail_evidence(self):
        products = {p["canonical_name"]: p for p in CATALOG["products"] if p.get("brand") == "Armaf"}
        for name, (concentration, _) in EXPECTED.items():
            with self.subTest(product=name):
                p = products[name]
                self.assertEqual(p["identity_status"], "source_verified_name")
                self.assertIn("/products/", p["source_url"])
                self.assertEqual(p["concentration"], concentration)

    def test_explicit_official_sizes_are_variants(self):
        products = {p["canonical_name"]: p for p in CATALOG["products"] if p.get("brand") == "Armaf"}
        for name, (_, expected_sizes) in EXPECTED.items():
            with self.subTest(product=name):
                p = products[name]
                sizes = {
                    v["size_ml"] for v in CATALOG["variants"]
                    if v["product_id"] == p["product_id"]
                }
                self.assertTrue(expected_sizes.issubset(sizes))

    def test_variants_inherit_officially_verified_concentration(self):
        products = {
            p["product_id"]: p
            for p in CATALOG["products"]
            if p.get("brand") == "Armaf"
        }
        for variant in CATALOG["variants"]:
            product = products.get(variant["product_id"])
            if not product or product["canonical_name"] not in EXPECTED:
                continue
            expected_concentration, expected_sizes = EXPECTED[product["canonical_name"]]
            if not expected_sizes:
                continue
            with self.subTest(variant=variant["variant_id"]):
                self.assertEqual(variant.get("concentration"), expected_concentration)
                self.assertEqual(variant.get("source_url"), product["source_url"])


if __name__ == "__main__":
    unittest.main()
