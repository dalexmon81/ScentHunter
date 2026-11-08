"""Regression checks for Paris Corner official detail-page evidence and line attribution."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Affogato Al Caffe": "Paris Corner",
    "Minya Caramel Dulce": "Minya",
    "Reham Rose Petals": "Reham",
    "Acadia Intenso Emir": "Emir",
    "Attractus": "Pendora Scents",
    "North Stag Hypnotic Oud Quinze XV": "North Stag",
}


class ParisCornerDetailEvidenceTests(unittest.TestCase):
    def test_selected_identities_have_official_product_page_evidence(self):
        products = {
            p["canonical_name"]: p
            for p in CATALOG["products"]
            if p.get("brand") == "Paris Corner"
        }
        for name, collection in EXPECTED.items():
            with self.subTest(product=name):
                p = products[name]
                self.assertEqual(p["identity_status"], "source_verified_name")
                self.assertIn("/products/", p["source_url"])
                self.assertEqual(p["collection_name"], collection)

    def test_explicit_100ml_sizes_are_variants(self):
        products = {
            p["canonical_name"]: p
            for p in CATALOG["products"]
            if p.get("brand") == "Paris Corner"
        }
        for name in EXPECTED:
            with self.subTest(product=name):
                p = products[name]
                variants = [
                    v for v in CATALOG["variants"]
                    if v["product_id"] == p["product_id"]
                ]
                self.assertTrue(any(v["size_ml"] == 100 for v in variants))
                self.assertTrue(all(v.get("source_url") for v in variants if v["size_ml"] == 100))


if __name__ == "__main__":
    unittest.main()
