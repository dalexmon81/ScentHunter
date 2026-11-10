"""Regression tests for the second Maison Asrar official product-page batch."""

import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Dubai Milano": ("https://maisonasrar.com/products/dubai-milano", None),
    "DXB": ("https://maisonasrar.com/products/dxb", None),
    "Emessa": ("https://maisonasrar.com/products/maison-asrar-emessa-eau-de-parfum-for-women", 100),
    "Fairy Tale": ("https://maisonasrar.com/products/fairy-tale-eau-de-perfum-100ml", 100),
    "Fakhama": ("https://maisonasrar.com/products/maison-asrar-fakhama-eau-de-parfum-100-ml-for-women", 100),
    "Faris Al Arab": ("https://maisonasrar.com/products/faris-al-arab", None),
    "Fresh Iris": ("https://maisonasrar.com/products/fresh-iris-maison-asrar-eau-de-perfum-100-ml", 100),
}


class MaisonAsrarOfficialProductPageBatchTwoTests(unittest.TestCase):
    def test_products_have_official_page_provenance(self):
        for name, (url, size) in EXPECTED.items():
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
                self.assertEqual(product["concentration"], "Eau de Parfum")

    def test_only_explicit_100ml_pages_create_variants(self):
        family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "maison_asrar_catalog"
        )
        registered = {p["canonical_name"]: p for p in family["products"]}
        for name, (url, size) in EXPECTED.items():
            product = next(
                p for p in CATALOG["products"]
                if p.get("brand_name") == "Maison Asrar"
                and p.get("canonical_name") == name
            )
            variants = [
                v for v in CATALOG["variants"]
                if v.get("product_id") == product["product_id"]
            ]
            with self.subTest(name=name):
                if size is None:
                    self.assertNotIn("formats_ml", product)
                    self.assertEqual(variants, [])
                    self.assertNotIn("formats_ml", registered[name])
                else:
                    self.assertEqual(product["formats_ml"], [100])
                    self.assertEqual(len(variants), 1)
                    self.assertEqual(variants[0]["size_ml"], 100)
                    self.assertEqual(variants[0]["concentration"], "Eau de Parfum")
                    self.assertEqual(variants[0]["source_evidence_url"], url)
                    self.assertEqual(registered[name]["formats_ml"], [100])


if __name__ == "__main__":
    unittest.main()
