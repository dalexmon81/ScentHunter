"""Regression coverage for Maison Asrar official product-detail provenance.

The official detail pages for these products identify the fragrance, but the
retrieved page specifications do not explicitly expose concentration or size.
Do not infer variant fields from collection names, prices, or URL slugs.
"""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
FAMILY_REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED_DETAIL_PAGES = {
    "Dubai London": "https://maisonasrar.com/products/dubai-london",
    "Dubai Miami": "https://maisonasrar.com/products/dubai-miami",
    "Hikaya": "https://maisonasrar.com/products/hikaya",
}


class MaisonAsrarOfficialDetailReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Maison Asrar"
        }
        cls.variants = CATALOG.get("variants", [])
        cls.family = next(
            (
                family for family in FAMILY_REGISTRY.get("families", [])
                if family.get("brand") == "Maison Asrar"
            ),
            None,
        )

    def test_existing_identities_are_upgraded_to_official_detail_pages(self):
        for name, source_url in EXPECTED_DETAIL_PAGES.items():
            with self.subTest(name=name):
                row = self.products.get(name)
                self.assertIsNotNone(row)
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source_url)
                self.assertEqual(row.get("source_product_url"), source_url)

    def test_no_size_or_concentration_is_inferred_without_variant_level_evidence(self):
        for name in EXPECTED_DETAIL_PAGES:
            with self.subTest(name=name):
                row = self.products[name]
                self.assertNotIn("formats_ml", row)
                self.assertNotIn("concentration", row)
                self.assertFalse(
                    any(variant.get("product_id") == row["product_id"] for variant in self.variants)
                )

    def test_upgraded_identities_remain_registered_in_maison_asrar_family(self):
        self.assertIsNotNone(self.family)
        family_names = {
            product.get("canonical_name")
            for product in self.family.get("products", [])
        }
        for name in EXPECTED_DETAIL_PAGES:
            with self.subTest(name=name):
                self.assertIn(name, family_names)


if __name__ == "__main__":
    unittest.main()
