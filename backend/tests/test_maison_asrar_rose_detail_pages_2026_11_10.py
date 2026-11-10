"""Regression checks for the two Rosé products verified from Maison Asrar pages."""

import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Rosé Absolute": "https://maisonasrar.com/products/absolute-eau-de-perfum-100ml",
    "Rosé Bouquet": "https://maisonasrar.com/products/bouquet-eau-de-perfum-100ml",
}


class MaisonAsrarRoseProductsTests(unittest.TestCase):
    def test_official_detail_pages_verify_existing_canonical_identities(self):
        for name, url in EXPECTED.items():
            with self.subTest(name=name):
                rows = [
                    p for p in CATALOG["products"]
                    if p.get("brand_name") == "Maison Asrar"
                    and p.get("canonical_name") == name
                ]
                self.assertEqual(len(rows), 1)
                product = rows[0]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_product_url"], url)
                self.assertEqual(product["source_evidence_url"], url)

    def test_no_variant_size_or_concentration_is_inferred(self):
        products = {
            p["canonical_name"]: p for p in CATALOG["products"]
            if p.get("brand_name") == "Maison Asrar"
        }
        for name in EXPECTED:
            with self.subTest(name=name):
                product_id = products[name]["product_id"]
                self.assertFalse([
                    v for v in CATALOG["variants"]
                    if v.get("product_id") == product_id
                ])

    def test_existing_family_registry_entries_are_preserved(self):
        family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "maison_asrar_catalog"
        )
        registered = {p["canonical_name"] for p in family["products"]}
        self.assertTrue(set(EXPECTED).issubset(registered))


if __name__ == "__main__":
    unittest.main()
