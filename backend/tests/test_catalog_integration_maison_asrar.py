"""Regression checks for Maison Asrar official detail-page provenance integration."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Dubai London": "https://maisonasrar.com/products/dubai-london",
    "Dubai Miami": "https://maisonasrar.com/products/dubai-miami",
    "Hikaya": "https://maisonasrar.com/products/hikaya",
}


class IntegratedMaisonAsrarProvenanceTests(unittest.TestCase):
    def test_existing_ids_are_source_verified_without_fabricated_variants(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "maison_asrar_catalog")
        family_names = {p["canonical_name"] for p in family["products"]}
        for name, url in EXPECTED.items():
            with self.subTest(name=name):
                matches = [
                    p for p in CATALOG["products"]
                    if p.get("brand") == "Maison Asrar" and p.get("canonical_name") == name
                ]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_product_url"], url)
                self.assertIn(name, family_names)
                self.assertNotIn("formats_ml", product)
                self.assertNotIn("concentration", product)
                self.assertFalse(any(v.get("product_id") == product["product_id"] for v in CATALOG["variants"]))


if __name__ == "__main__":
    unittest.main()
