"""Regression checks for integrated, official Velixir Sacred Four variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Comus": ("SH-VELIXIR-50b87cfb", {35, 100}),
    "Ether": ("SH-VELIXIR-36e7a5ca", {35, 100}),
    "Panacea": ("SH-VELIXIR-1738e7af", {35, 100}),
}


class IntegratedVelixirVariantTests(unittest.TestCase):
    def test_variants_are_integrated_once_and_keep_canonical_ids(self):
        for name, (product_id, sizes) in EXPECTED.items():
            with self.subTest(name=name):
                products = [
                    p for p in CATALOG["products"]
                    if p.get("brand") == "Velixir" and p.get("canonical_name") == name
                ]
                self.assertEqual(len(products), 1)
                self.assertEqual(products[0]["product_id"], product_id)
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == product_id]
                self.assertEqual({v["size_ml"] for v in variants}, sizes)
                self.assertEqual(len(variants), len(sizes))
                self.assertTrue(all(v.get("concentration") == "Extrait de Parfum" for v in variants))
                self.assertTrue(all(v.get("source_evidence_url") == f"https://velixirparfums.store/products/{name.lower()}" for v in variants))

    def test_family_registry_matches_verified_sizes(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "velixir_catalog")
        products = {p.get("canonical_name"): p for p in family.get("products", [])}
        for name in EXPECTED:
            with self.subTest(name=name):
                self.assertEqual(set(products[name].get("formats_ml", [])), {35, 100})


if __name__ == "__main__":
    unittest.main()
