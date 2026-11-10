"""Regression coverage for seven Khadlaj official product-page reconciliations."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Nuha Bon Bon": {
        "id": "SH-KHADLAJ-7ecbb58c",
        "url": "https://khadlaj-perfumes.com/products/nuha-bon-bon-strawberry-vanilla-ice-cream-gourmand-perfume-for-women-online",
        "size": 85,
        "concentration": "Eau de Parfum",
        "gtin": "6298043070317"
    },
    "Nuha Cherry Blush": {
        "id": "SH-KHADLAJ-37d5907b",
        "url": "https://khadlaj-perfumes.com/products/nuha-cherry-blush-85-ml-edp-spray-for-women-online-shopping-uae",
        "size": 85,
        "concentration": "Eau de Parfum",
        "gtin": "6291107979175"
    },
    "Strawberry Shake": {
        "id": "SH-KHADLAJ-STRAWBERRY-SHAKE",
        "url": "https://khadlaj-perfumes.com/products/strawberry-shake-eau-de-parfum-spray-for-women-dubai-uae-online",
        "size": 100,
        "concentration": "Eau de Parfum",
        "gtin": "6298043070652"
    },
    "Nafais Magrib": {
        "id": "SH-KHADLAJ-NAFAIS-MAGRIB",
        "url": "https://khadlaj-perfumes.com/collections/unisex-1/products/khadlaj-nafais-magrib-100-ml-eau-de-parfum-for-men-women",
        "size": 100,
        "concentration": "Eau de Parfum",
        "gtin": "6298043070010"
    },
    "Mansion": {
        "id": "SH-KHADLAJ-MANSION",
        "url": "https://khadlaj-perfumes.com/collections/unisex-1/products/mansion-eau-de-parfum-spray-for-unisex-scents-by-khadlaj-dubai-uae",
        "size": 100,
        "concentration": "Eau de Parfum",
        "gtin": "6298043070331"
    },
    "Peach Velvet": {
        "id": "SH-KHADLAJ-PEACH-VELVET",
        "url": "https://khadlaj-perfumes.com/collections/best-selling-perfumes/products/peach-velvet-100-ml-extrait-de-parfum-for-women-top-women-fragrance-brand-uae",
        "size": 100,
        "concentration": "Extrait de Parfum",
        "gtin": "6298043070034"
    },
    "Onyx Gold": {
        "id": "SH-KHADLAJ-6494ea68",
        "url": "https://khadlaj-perfumes.com/ar/collections/for-him/products/khadlaj-onyx-gold-100-ml-eau-de-parfum-for-men-luxury-perfume-online-dubai-uae",
        "size": 100,
        "concentration": "Eau de Parfum",
        "gtin": "6298043070140"
    }
}


class KhadlajSevenOfficialVariantsTests(unittest.TestCase):
    def test_existing_canonical_identities_have_official_detail_provenance(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                products = [
                    p for p in CATALOG["products"]
                    if p.get("brand") == "Khadlaj" and p.get("canonical_name") == name
                ]
                self.assertEqual(len(products), 1)
                product = products[0]
                self.assertEqual(product["product_id"], expected["id"])
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], expected["url"])
                self.assertEqual(product["source_product_url"], expected["url"])
                self.assertEqual(product["source_evidence_url"], expected["url"])
                self.assertEqual(product["concentration"], expected["concentration"])
                self.assertEqual(product["formats_ml"], [expected["size"]])

    def test_exactly_one_variant_has_official_gtin_and_page_evidence(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                product = next(
                    p for p in CATALOG["products"]
                    if p.get("brand") == "Khadlaj" and p.get("canonical_name") == name
                )
                variants = [
                    v for v in CATALOG["variants"]
                    if v.get("product_id") == product["product_id"]
                ]
                self.assertEqual(len(variants), 1)
                variant = variants[0]
                self.assertEqual(variant["size_ml"], expected["size"])
                self.assertEqual(variant["concentration"], expected["concentration"])
                self.assertEqual(variant["gtin"], expected["gtin"])
                self.assertEqual(variant["source_url"], expected["url"])
                self.assertEqual(variant["source_evidence_url"], expected["url"])

    def test_all_matching_khadlaj_family_registry_rows_include_verified_size(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                matches = [
                    p for family in REGISTRY["families"]
                    for p in family.get("products", [])
                    if p.get("canonical_name") == name
                ]
                self.assertGreaterEqual(len(matches), 1)
                for product in matches:
                    self.assertIn(expected["size"], product.get("formats_ml", []))


if __name__ == "__main__":
    unittest.main()
