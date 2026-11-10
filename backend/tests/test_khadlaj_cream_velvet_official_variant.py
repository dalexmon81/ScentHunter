"""Regression coverage for three Khadlaj official product-page reconciliations."""
# NOTE: Keep this module and the workflow test list in sync; CI must not reference
# an absent test module.
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Cream Velvet": {
        "id": "SH-KHADLAJ-142e4d1e",
        "url": "https://khadlaj-perfumes.com/products/cream-velvet-100-ml-extrait-de-parfum-for-women-best-perfumes",
        "gtin": "6291107978819"
    },
    "Island": {
        "id": "SH-KHADLAJ-d348f0b3",
        "url": "https://khadlaj-perfumes.com/collections/all/products/island-100-ml-extrait-de-parfum-spray-for-men-and-women",
        "gtin": "6291107978789"
    },
    "Island Sun": {
        "id": "SH-KHADLAJ-93c5a51d",
        "url": "https://khadlaj-perfumes.com/products/khadlaj-island-sun-100-ml-extrait-de-parfum",
        "gtin": "6298043073080"
    }
}


class KhadlajOfficialProductReconciliationTests(unittest.TestCase):
    def test_existing_identities_have_official_detail_provenance(self):
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
                self.assertEqual(product["concentration"], "Extrait de Parfum")
                self.assertEqual(product["formats_ml"], [100])

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
                self.assertEqual(variant["size_ml"], 100)
                self.assertEqual(variant["concentration"], "Extrait de Parfum")
                self.assertEqual(variant["gtin"], expected["gtin"])
                self.assertEqual(variant["source_url"], expected["url"])
                self.assertEqual(variant["source_evidence_url"], expected["url"])

    def test_khadlaj_family_registry_matches_the_verified_size(self):
        family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "khadlaj_catalog"
        )
        for name in EXPECTED:
            with self.subTest(product=name):
                matches = [
                    p for p in family["products"]
                    if p.get("canonical_name") == name
                ]
                self.assertEqual(len(matches), 1)
                self.assertIn(100, matches[0].get("formats_ml", []))


if __name__ == "__main__":
    unittest.main()
