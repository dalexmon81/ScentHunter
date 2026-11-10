"""Regression tests for five Khadlaj official product-page variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Muse": {"id": "SH-KHADLAJ-MUSE", "size": 100, "concentration": "Eau de Parfum", "gtin": "6298043072748", "variant_id": "SHV-SH-KHADLAJ-MUSE-100-EDP", "url": "https://khadlaj-perfumes.com/products/khadlaj-muse-100-ml-eau-de-parfum-spray-for-women"},
    "Sueno": {"id": "SH-KHADLAJ-SUENO", "size": 100, "concentration": "Extrait de Parfum", "gtin": "6298043072809", "variant_id": "SHV-SH-KHADLAJ-SUENO-100-EXTRAIT", "url": "https://khadlaj-perfumes.com/collections/all/products/sueno-100ml-extrait-de-parfum-for-women"},
    "Saraya": {"id": "SH-KHADLAJ-SARAYA", "size": 60, "concentration": "Extrait de Parfum", "gtin": "6298043072380", "variant_id": "SHV-SH-KHADLAJ-SARAYA-60-EXTRAIT", "url": "https://khadlaj-perfumes.com/products/khadlaj-saraya-60-ml-extrait-de-parfum-spray-for-men-women"},
    "Strawberry Shake": {"id": "SH-KHADLAJ-STRAWBERRY-SHAKE", "size": 100, "concentration": "Eau de Parfum", "gtin": "6298043070652", "variant_id": "SHV-SH-KHADLAJ-STRAWBERRY-SHAKE-100-EDP", "url": "https://khadlaj-perfumes.com/products/strawberry-shake-eau-de-parfum-spray-for-women-dubai-uae-online"},
    "Peach Velvet": {"id": "SH-KHADLAJ-PEACH-VELVET", "size": 100, "concentration": "Extrait de Parfum", "gtin": "6298043070034", "variant_id": "SHV-SH-KHADLAJ-PEACH-VELVET-100-EXTRAIT", "url": "https://khadlaj-perfumes.com/products/peach-velvet-100-ml-extrait-de-parfum-for-women-top-women-fragrance-brand-uae"},
}

class KhadlajOfficialVariantBatchTests(unittest.TestCase):
    def test_existing_identities_are_upgraded_with_official_page_evidence(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                products = [p for p in CATALOG["products"] if p.get("brand") == "Khadlaj" and p.get("canonical_name") == name]
                self.assertEqual(len(products), 1)
                product = products[0]
                self.assertEqual(product["product_id"], expected["id"])
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], expected["url"])
                self.assertEqual(product["source_product_url"], expected["url"])
                self.assertEqual(product["source_evidence_url"], expected["url"])
                self.assertEqual(product["concentration"], expected["concentration"])
                self.assertEqual(product["formats_ml"], [expected["size"]])

    def test_exactly_one_variant_per_identity_has_official_gtin_and_page_evidence(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == expected["id"]]
                self.assertEqual(len(variants), 1)
                variant = variants[0]
                self.assertEqual(variant["variant_id"], expected["variant_id"])
                self.assertEqual(variant["size_ml"], expected["size"])
                self.assertEqual(variant["concentration"], expected["concentration"])
                self.assertEqual(variant["gtin"], expected["gtin"])
                self.assertEqual(variant["source_url"], expected["url"])
                self.assertEqual(variant["source_evidence_url"], expected["url"])

    def test_family_registry_formats_match_official_variants(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "khadlaj_catalog")
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                rows = [p for p in family["products"] if p.get("canonical_name") == name]
                self.assertEqual(len(rows), 1)
                self.assertIn(expected["size"], rows[0].get("formats_ml", []))

if __name__ == "__main__":
    unittest.main()
