"""Regression tests for Khadlaj official product-detail reconciliations."""

import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Biscotti Date Toffee": (
        "SH-KHADLAJ-75815e2a",
        "SHV-SH-KHADLAJ-75815e2a-100-000",
        "https://khadlaj-perfumes.com/products/biscotti-date-toffee-100-ml-extrait-de-parfum-spray-for-unisex-gourmand-lover-fragrances",
        100,
        "Extrait de Parfum",
        "6291107979977",
    ),
    "Private Blend Musk Ice": (
        "SH-KHADLAJ-dd1434f1",
        "SHV-SH-KHADLAJ-dd1434f1-100-000",
        "https://khadlaj-perfumes.com/products/private-blend-musk-ice-extrait-de-parfum-100-ml-designer-fragrance",
        100,
        "Extrait de Parfum",
        "6291107979410",
    ),
    "Musk Pure Musk Blend": (
        "SH-KHADLAJ-04832397",
        "SHV-SH-KHADLAJ-04832397-60-000",
        "https://khadlaj-perfumes.com/products/musk-pure-musk-blend-creation-of-iqbal-65-ml-edp-spray-perfume-for-men-and-women-online-dubai-uae",
        60,
        "Eau de Parfum",
        "6291107978154",
    ),
}


class KhadlajOfficialDetailTests(unittest.TestCase):
    def test_canonical_products_and_variants_match_official_pages(self):
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
