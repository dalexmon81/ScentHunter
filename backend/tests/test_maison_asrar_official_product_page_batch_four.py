"""Regression coverage for Maison Asrar Hamsat, Harmony and related page batch."""

import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Hamsat Ghazal": ("https://maisonasrar.com/products/maison-asrar-hamsat-ghazal-eau-de-parfum-100-ml-for-women", 100),
    "Hamsat Hob": ("https://maisonasrar.com/products/maison-asrar-hamsat-hob-eau-de-parfum-100-ml-for-women", 100),
    "Hamsat Ishq": ("https://maisonasrar.com/products/maison-asrar-hamsat-ishq-eau-de-parfum-100-ml-for-women", 100),
    "Harmony": ("https://maisonasrar.com/products/harmony", None),
    "Heritage": ("https://maisonasrar.com/products/maison-asrar-heritage-eau-de-parfum-100-ml-unisex", 100),
    "Hikaya": ("https://maisonasrar.com/products/hikaya", None),
    "Hilm": ("https://maisonasrar.com/products/hilm", None),
    "Hunter": ("https://maisonasrar.com/products/maison-asrar-hunter-eau-de-parfum-100ml", 100),
    "Icon": ("https://maisonasrar.com/products/icon-eau-de-perfum-100ml", 100),
}


class MaisonAsrarOfficialProductPageBatchFourTests(unittest.TestCase):
    def test_official_page_provenance_is_attached_to_existing_identity(self):
        for name, (url, size) in EXPECTED.items():
            with self.subTest(name=name):
                rows = [
                    p for p in CATALOG["products"]
                    if p.get("brand_name") == "Maison Asrar"
                    and p.get("canonical_name") == name
                ]
                self.assertEqual(len(rows), 1)
                p = rows[0]
                self.assertEqual(p["identity_status"], "source_verified_name")
                self.assertEqual(p["source_url"], url)
                self.assertEqual(p["source_product_url"], url)
                self.assertEqual(p["source_evidence_url"], url)

    def test_only_explicit_size_pages_create_100ml_edp_variants(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "maison_asrar_catalog")
        registered = {p["canonical_name"]: p for p in family["products"]}
        for name, (url, size) in EXPECTED.items():
            product = next(
                p for p in CATALOG["products"]
                if p.get("brand_name") == "Maison Asrar" and p.get("canonical_name") == name
            )
            variants = [v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]]
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
