"""Regression coverage for Maison Asrar official product-page verification batch."""

import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

VERIFIED = {
    "1963": ("https://maisonasrar.com/products/1963-eau-de-perfum-100ml", 100),
    "Adorable": ("https://maisonasrar.com/products/adorable-eau-de-parfum-100-ml-for-women", 100),
    "Alonoud": ("https://maisonasrar.com/products/maison-asrar-alonoud-eau-de-parfum-100-ml-for-women", 100),
    "Aseel": ("https://maisonasrar.com/products/aseel", None),
    "Basma": ("https://maisonasrar.com/products/maison-asrar-basma-eau-de-parfum-100-ml-unisex", 100),
    "Black": ("https://maisonasrar.com/products/black-eau-de-perfum-100ml", 100),
    "Bloom Bloom": ("https://maisonasrar.com/products/bloom-bloom-eau-de-parfum-100ml", 100),
    "Bonita": ("https://maisonasrar.com/products/bonita-eau-de-parfum-100ml", 100),
    "Casablanca": ("https://maisonasrar.com/products/casablanca-maison-asrar-eau-de-perfum-100ml", 100),
    "Cascade": ("https://maisonasrar.com/products/cascade", None),
}


class MaisonAsrarOfficialProductPageBatchTests(unittest.TestCase):
    def test_official_product_page_provenance_is_recorded_once(self):
        for name, (url, size) in VERIFIED.items():
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

    def test_explicit_100ml_edp_pages_have_one_matching_variant(self):
        family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "maison_asrar_catalog"
        )
        registered = {p["canonical_name"]: p for p in family["products"]}
        for name, (url, size) in VERIFIED.items():
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
                    self.assertNotIn("concentration", product)
                    self.assertEqual(variants, [])
                    self.assertNotIn("formats_ml", registered[name])
                else:
                    self.assertEqual(product["formats_ml"], [100])
                    self.assertEqual(product["concentration"], "Eau de Parfum")
                    self.assertEqual(len(variants), 1)
                    self.assertEqual(variants[0]["size_ml"], 100)
                    self.assertEqual(variants[0]["concentration"], "Eau de Parfum")
                    self.assertEqual(variants[0]["source_evidence_url"], url)
                    self.assertEqual(registered[name]["formats_ml"], [100])


if __name__ == "__main__":
    unittest.main()
