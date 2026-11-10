"""Regression tests for three additional Khadlaj official product pages."""

import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Titan": ("SH-KHADLAJ-ce6dbd60", "SHV-SH-KHADLAJ-ce6dbd60-100-000", "https://khadlaj-perfumes.com/products/khadlaj-titan-100-ml-eau-de-parfum-spray-for-men-refreshing-scents-to-buy-online-dubai-uae", 100, "Eau de Parfum", "6298043070065"),
    "Nuha Cherry Blush": ("SH-KHADLAJ-37d5907b", "SHV-SH-KHADLAJ-37d5907b-85-EDP", "https://khadlaj-perfumes.com/products/nuha-cherry-blush-85-ml-edp-spray-for-women-online-shopping-uae", 85, "Eau de Parfum", "6291107979175"),
    "Onyx Gold": ("SH-KHADLAJ-6494ea68", "SHV-SH-KHADLAJ-6494ea68-100-EDP", "https://khadlaj-perfumes.com/products/khadlaj-onyx-gold-100-ml-eau-de-parfum-for-men-luxury-perfume-online-dubai-uae", 100, "Eau de Parfum", "6298043070140"),
}


class KhadlajThreeMoreOfficialVariantsTests(unittest.TestCase):
    def test_products_variants_and_family_registry_are_aligned(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "khadlaj_catalog")
        registry = {p["canonical_name"]: p for p in family["products"]}
        for name, (product_id, variant_id, url, size, concentration, gtin) in EXPECTED.items():
            with self.subTest(name=name):
                products = [p for p in CATALOG["products"] if p.get("product_id") == product_id]
                self.assertEqual(len(products), 1)
                product = products[0]
                self.assertEqual(product["canonical_name"], name)
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_product_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertEqual(product["formats_ml"], [size])
                self.assertEqual(product["concentration"], concentration)

                variants = [v for v in CATALOG["variants"] if v.get("product_id") == product_id]
                self.assertEqual(len(variants), 1)
                variant = variants[0]
                self.assertEqual(variant["variant_id"], variant_id)
                self.assertEqual(variant["size_ml"], size)
                self.assertEqual(variant["concentration"], concentration)
                self.assertEqual(variant["gtin"], gtin)
                self.assertEqual(variant["source_evidence_url"], url)
                self.assertEqual(registry[name]["formats_ml"], [size])


if __name__ == "__main__":
    unittest.main()
