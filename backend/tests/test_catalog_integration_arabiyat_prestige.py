"""Regression coverage for integrated Arabiyat Prestige New Launch variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Aariz": ("SH-ARABIYAT-PRESTIGE-00d6e7bc", "https://arabiyatprestige.com/collections/new-launch/products/aariz-100ml", 100),
    "Aariz L’Absolu": ("SH-ARABIYAT-PRESTIGE-5ea21b51", "https://arabiyatprestige.com/collections/new-launch/products/arabiyat-prestige-aariz-l-absolu-edp-100-ml-unisex", 100),
    "Asháa Oud Noir": ("SH-ARABIYAT-PRESTIGE-641acbf3", "https://arabiyatprestige.com/collections/new-launch/products/ashaa-oud-noir-edp-110ml", 110),
    "Marwa": ("SH-ARABIYAT-PRESTIGE-7bf3b46e", "https://arabiyatprestige.com/collections/new-launch/products/arabiyat-prestige-marwa-edp-100ml-unisex", 100),
    "Kohl Opulence": ("SH-ARABIYAT-PRESTIGE-113b2420", "https://arabiyatprestige.com/collections/new-launch/products/arabiyat-prestige-kohl-opulence-edp-100-ml-unisex", 100),
}


class IntegratedArabiyatPrestigeTests(unittest.TestCase):
    def test_each_product_has_one_stable_source_verified_identity(self):
        for name, (product_id, url, size) in EXPECTED.items():
            with self.subTest(name=name):
                matches = [
                    p for p in CATALOG["products"]
                    if p.get("brand") == "Arabiyat Prestige" and p.get("canonical_name") == name
                ]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product["product_id"], product_id)
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_product_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertEqual(product["concentration"], "Eau de Parfum")
                self.assertEqual(product["formats_ml"], [size])

    def test_variants_and_registry_match_official_evidence(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "arabiyat_prestige_catalog")
        family_products = {p["canonical_name"]: p for p in family["products"]}
        for name, (product_id, url, size) in EXPECTED.items():
            with self.subTest(name=name):
                variants = [v for v in CATALOG["variants"] if v["product_id"] == product_id]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0]["size_ml"], size)
                self.assertEqual(variants[0]["concentration"], "Eau de Parfum")
                self.assertEqual(variants[0]["source_evidence_url"], url)
                self.assertEqual(family_products[name]["formats_ml"], [size])


if __name__ == "__main__":
    unittest.main()
