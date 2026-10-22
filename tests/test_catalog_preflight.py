"""Tests for the read-only canonical catalog structural preflight."""
import unittest

from backend.scenthunter_next_engine.catalog_preflight import audit_catalog_data


class CatalogPreflightTests(unittest.TestCase):
    def test_clean_catalog_shape_is_reported_without_mutation(self):
        source = {
            "schema_version": 1,
            "products": [{
                "product_id": "p1", "canonical_name": "Example",
                "brand_id": "b1", "canonical_image": "https://example.test/p.jpg",
            }],
            "variants": [{"variant_id": "v1", "product_id": "p1", "size_ml": 100}],
        }
        before = repr(source)
        report = audit_catalog_data(source)
        self.assertEqual(report["product_count"], 1)
        self.assertEqual(report["variant_count"], 1)
        self.assertEqual(report["findings"], [])
        self.assertTrue(report["safe_to_consider_migration"])
        self.assertTrue(report["read_only"])
        self.assertEqual(report["automatic_repairs"], 0)
        self.assertEqual(repr(source), before)

    def test_duplicate_ids_orphan_and_missing_fields_are_reported(self):
        source = {
            "products": [
                {"product_id": "p1", "canonical_name": "One", "brand_id": "b1"},
                {"product_id": "p1", "canonical_name": "Two", "brand_id": "b1"},
            ],
            "variants": [
                {"variant_id": "v1", "product_id": "missing"},
                {"variant_id": "v1", "product_id": "p1"},
            ],
        }
        report = audit_catalog_data(source)
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("duplicate_product_ids", codes)
        self.assertIn("duplicate_variant_ids", codes)
        self.assertIn("orphan_variants", codes)
        self.assertIn("variants_missing_size", codes)
        self.assertFalse(report["safe_to_consider_migration"])

    def test_invalid_root_and_missing_arrays_fail_closed(self):
        with self.assertRaises(ValueError):
            audit_catalog_data([])
        with self.assertRaises(ValueError):
            audit_catalog_data({"products": []})

    def test_invalid_variant_sizes_are_reported_without_mutation(self):
        invalid_values = [0, -1, "abc", " ", True, float("inf"), float("nan")]
        source = {
            "products": [{
                "product_id": "p1", "canonical_name": "Example",
                "brand_id": "b1", "canonical_image": "https://example.test/p.jpg",
            }],
            "variants": [
                {"variant_id": f"v{i}", "product_id": "p1", "size_ml": value}
                for i, value in enumerate(invalid_values)
            ],
        }
        before = repr(source)
        report = audit_catalog_data(source)
        findings = {item["code"]: item["count"] for item in report["findings"]}
        self.assertEqual(findings["variants_invalid_size"], len(invalid_values))
        self.assertNotIn("variants_missing_size", findings)
        self.assertFalse(report["safe_to_consider_migration"])
        self.assertTrue(report["read_only"])
        self.assertEqual(report["automatic_repairs"], 0)
        self.assertEqual(repr(source), before)

    def test_missing_and_invalid_sizes_are_counted_separately(self):
        source = {
            "products": [{"product_id": "p1", "canonical_name": "Example", "brand_id": "b1"}],
            "variants": [
                {"variant_id": "v1", "product_id": "p1", "size_ml": None},
                {"variant_id": "v2", "product_id": "p1", "size_ml": ""},
                {"variant_id": "v3", "product_id": "p1", "size_ml": -5},
            ],
        }
        report = audit_catalog_data(source)
        findings = {item["code"]: item["count"] for item in report["findings"]}
        self.assertEqual(findings["variants_missing_size"], 2)
        self.assertEqual(findings["variants_invalid_size"], 1)


if __name__ == "__main__":
    unittest.main()
