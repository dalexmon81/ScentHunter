"""Monotonic quality-debt budgets for the canonical catalog seed.

These ceilings capture the audited 10 Nov 2026 baseline. They are not claims
that every legacy record is wrong: missing concentration or variant data must
remain unset when first-party evidence does not establish it. New work must
not increase these backlogs; subsequent verified audits should lower them.
"""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))


class CatalogQualityDebtBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.products_by_id = {p["product_id"]: p for p in cls.products}
        cls.products_with_variants = {v["product_id"] for v in cls.variants}

    def test_source_listed_identity_backlog_does_not_grow(self):
        listed = [p for p in self.products if p.get("identity_status") == "source_listed_name"]
        self.assertLessEqual(len(listed), 1153)

    def test_verified_products_without_variants_backlog_does_not_grow(self):
        pending = [
            p for p in self.products
            if p.get("identity_status") == "source_verified_name"
            and p["product_id"] not in self.products_with_variants
        ]
        self.assertLessEqual(len(pending), 253)

    def test_variants_without_any_source_url_do_not_increase(self):
        missing = [
            v for v in self.variants
            if not (v.get("source_evidence_url") or v.get("source_url") or v.get("source_product_url"))
        ]
        self.assertLessEqual(len(missing), 146)

    def test_variants_without_explicit_concentration_do_not_increase(self):
        missing = [v for v in self.variants if not v.get("concentration")]
        self.assertLessEqual(len(missing), 381)

    def test_variant_ids_and_product_size_concentration_tuples_are_unique(self):
        variant_ids = [v["variant_id"] for v in self.variants]
        tuples = [
            (v["product_id"], v["size_ml"], v.get("concentration"))
            for v in self.variants
        ]
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertEqual(len(tuples), len(set(tuples)))

    def test_every_variant_is_attached_to_a_canonical_product(self):
        for variant in self.variants:
            with self.subTest(variant_id=variant.get("variant_id")):
                self.assertIn(variant["product_id"], self.products_by_id)

    def test_variant_records_remain_free_of_commercial_offer_data(self):
        offer_fields = {"price", "stock", "availability", "shipping_cost", "store_url", "retailer"}
        for variant in self.variants:
            with self.subTest(variant_id=variant.get("variant_id")):
                self.assertTrue(offer_fields.isdisjoint(variant))


if __name__ == "__main__":
    unittest.main()
