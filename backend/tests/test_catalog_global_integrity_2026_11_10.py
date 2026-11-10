"""Strict global invariants for the canonical catalog and family registry.

This module deliberately validates structural correctness and separation from
commercial offer data. Source gaps are not filled by guessing.
"""
import json
import re
import unicodedata
import unittest
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

FORBIDDEN_VARIANT_FIELDS = {
    "price", "price_amount", "currency", "availability", "stock", "in_stock",
    "offer_url", "retailer", "store_id", "shipping_cost", "shipping",
}


def normalize(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def duplicates(values):
    return {value: count for value, count in Counter(values).items() if count > 1}


class CatalogGlobalIntegrityAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.families = REGISTRY["families"]
        cls.products_by_id = {row["product_id"]: row for row in cls.products}
        cls.families_by_id = {row["family_id"]: row for row in cls.families}

    def test_product_ids_variant_ids_and_normalized_identities_are_unique(self):
        self.assertFalse(duplicates(row["product_id"] for row in self.products))
        self.assertFalse(duplicates(row["variant_id"] for row in self.variants))
        identities = (
            (normalize(row.get("brand_name") or row.get("brand")),
             normalize(row.get("canonical_name") or row.get("name")))
            for row in self.products
        )
        self.assertFalse(duplicates(identities))

    def test_variant_tuples_and_nonempty_gtins_are_unique(self):
        tuples = (
            (row["product_id"], row["size_ml"], row.get("concentration"))
            for row in self.variants
        )
        gtins = (row["gtin"] for row in self.variants if row.get("gtin"))
        self.assertFalse(duplicates(tuples))
        self.assertFalse(duplicates(gtins))

    def test_every_variant_has_a_product_parent_and_valid_declared_size(self):
        for variant in self.variants:
            with self.subTest(variant_id=variant.get("variant_id")):
                product = self.products_by_id.get(variant.get("product_id"))
                self.assertIsNotNone(product)
                formats = product.get("formats_ml")
                if formats is not None:
                    self.assertIn(variant.get("size_ml"), formats)

    def test_every_product_maps_to_exactly_one_family_registry_identity(self):
        family_row_counts = Counter()
        for family in self.families:
            family_row_counts[family["family_id"]] += 1
            normalized_names = [
                normalize(row.get("canonical_name"))
                for row in family.get("products", [])
            ]
            self.assertFalse(duplicates(normalized_names), family["family_id"])
        self.assertFalse(duplicates(row["family_id"] for row in self.families))
        for product in self.products:
            family = self.families_by_id.get(product.get("family_id"))
            self.assertIsNotNone(family, product.get("product_id"))
            name = normalize(product.get("canonical_name") or product.get("name"))
            matches = [
                row for row in family.get("products", [])
                if normalize(row.get("canonical_name")) == name
                or any(normalize(alias) == name for alias in row.get("aliases", []))
            ]
            with self.subTest(product_id=product.get("product_id")):
                self.assertEqual(len(matches), 1)

    def test_canonical_variants_do_not_contain_commercial_offer_data(self):
        for variant in self.variants:
            forbidden = FORBIDDEN_VARIANT_FIELDS.intersection(variant)
            with self.subTest(variant_id=variant.get("variant_id")):
                self.assertFalse(forbidden, sorted(forbidden))

    def test_catalog_has_minimum_cumulative_snapshot_coverage(self):
        self.assertGreaterEqual(len(self.products), 2213)
        self.assertGreaterEqual(len(self.variants), 1160)
        self.assertGreaterEqual(len(self.families), 34)

    def test_quality_debt_remains_below_audited_ceilings(self):
        products_with_variants = {row["product_id"] for row in self.variants}
        listed = [row for row in self.products if row.get("identity_status") == "source_listed_name"]
        verified_pending = [
            row for row in self.products
            if row.get("identity_status") == "source_verified_name"
            and row["product_id"] not in products_with_variants
        ]
        missing_variant_sources = [
            row for row in self.variants
            if not (row.get("source_evidence_url") or row.get("source_url")
                    or row.get("source_product_url"))
        ]
        unspecified_concentration = [
            row for row in self.variants if not row.get("concentration")
        ]
        self.assertLessEqual(len(listed), 974)
        self.assertLessEqual(len(verified_pending), 241)
        self.assertLessEqual(len(missing_variant_sources), 146)
        self.assertLessEqual(len(unspecified_concentration), 381)


if __name__ == "__main__":
    unittest.main()
