from __future__ import annotations

import unittest

from backend.scenthunter_next_engine.validate_migration_plan import (
    validate_migration_plan,
    validate_plan_counts,
)


def valid_report() -> dict:
    return {
        "status": "complete",
        "read_only": True,
        "catalog_mutated": False,
        "database_mutated": False,
        "automatic_repairs": 0,
        "product_count": 2,
        "variant_count": 1,
        "products_without_variants": {
            "count": 1,
            "records": [{"product_id": "p2"}],
        },
        "products_missing_canonical_image": {
            "count": 1,
            "records": [{"product_id": "p2"}],
        },
        "records_requiring_review": {
            "count": 1,
            "records": [{"product_id": "p2", "review_reasons": ["no_explicit_variant_records"]}],
        },
        "migration_gate": {
            "allowed": False,
            "reason": "Human review is required before migration.",
        },
    }


class MigrationPlanValidatorTests(unittest.TestCase):
    def test_accepts_consistent_read_only_plan(self) -> None:
        report = valid_report()
        self.assertEqual(validate_migration_plan(report), [])
        result = validate_plan_counts(report)
        self.assertEqual(result["status"], "valid")
        self.assertFalse(result["migration_allowed"])

    def test_rejects_mutation_flags(self) -> None:
        report = valid_report()
        report["catalog_mutated"] = True
        self.assertIn("catalog_mutation_flag_not_false", validate_migration_plan(report))

    def test_rejects_open_migration_gate(self) -> None:
        report = valid_report()
        report["migration_gate"]["allowed"] = True
        self.assertIn("migration_gate_must_remain_closed", validate_migration_plan(report))

    def test_rejects_count_mismatch(self) -> None:
        report = valid_report()
        report["products_without_variants"]["count"] = 2
        self.assertIn("products_without_variants_count_mismatch", validate_migration_plan(report))

    def test_rejects_duplicate_product_ids_in_report_section(self) -> None:
        report = valid_report()
        report["products_without_variants"]["records"] = [
            {"product_id": "p2"},
            {"product_id": "p2"},
        ]
        report["products_without_variants"]["count"] = 2
        self.assertIn("duplicate_ids_in_no_variant_records", validate_migration_plan(report))

    def test_rejects_missing_gate_reason(self) -> None:
        report = valid_report()
        report["migration_gate"]["reason"] = " "
        self.assertIn("migration_gate_reason_missing", validate_migration_plan(report))


if __name__ == "__main__":
    unittest.main()
