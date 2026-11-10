"""Regression coverage for Maison Asrar Gentle Oud and Hamsat Gharam variants."""

import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Gentle Oud": ("https://maisonasrar.com/products/maison-asrar-gentle-oud-eau-de-parfum-80-ml-for-men", 80),
    "Hamsat Gharam": ("https://maisonasrar.com/products/maison-asrar-hamsat-gharam-eau-de-parfum-100-ml-for-women", 100),
}


class MaisonAsrarOfficialSizeVariantTests(unittest.TestCase):
    def test_individual_official_pages_define_identity_and_size(self):
        family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "maison_asrar_catalog"
        )
        registered = {p["canonical_name"]: p for p in family["products"]}
        for name, (url, size) in EXPECTED.items():
            with self.subTest(name=name):
                product = next(
                    p for p in CATALOG["products"]
                    if p.get("brand_name") == "Maison Asrar"
                    and p.get("canonical_name") == name
                )
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_product_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertEqual(product["concentration"], "Eau de Parfum")
                self.assertEqual(product["formats_ml"], [size])
                variants = [
                    v for v in CATALOG["variants"]
                    if v.get("product_id") == product["product_id"]
                ]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0]["size_ml"], size)
                self.assertEqual(variants[0]["concentration"], "Eau de Parfum")
                self.assertEqual(variants[0]["source_evidence_url"], url)
                self.assertEqual(registered[name]["formats_ml"], [size])


if __name__ == "__main__":
    unittest.main()
