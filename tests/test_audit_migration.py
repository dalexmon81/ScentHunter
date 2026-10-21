"""Tests for the read-only migration report consistency audit."""

import unittest

from backend.scenthunter_next_engine.audit_migration_reports import audit_reports


def group(records):
    return {"count": len(records), "all_records": records}


def make_reports():
    detail = {
        "product_count": 3,
        "variant_count": 2,
        "products_without_variants": group([{"product_id": "p1"}]),
        "products_missing_canonical_image": group([{"product_id": "p2"}]),
        "orphan_variants": group([]),
        "products_missing_brand": group([]),
        "products_missing_name": group([]),
    }
    plan = {
        "status": "complete",
        "read_only": True,
        "catalog_mutated": False,
        "database_mutated": False,
        "automatic_repairs": 0,
        "migration_gate": {"allowed": False},
        "product_count": 3,
        "variant_count": 2,
        "records_requiring_review": [
            {"product_id": "p1"},
            {"product_id": "p2"},
        ],
        "records_requiring_review_count": 2,
        "review_reasons": {
            "no_explicit_variant_records": 1,
            "missing_canonical_image": 1,
        },
    }
    return detail, plan


class TestMigrationReportAudit(unittest.TestCase):
    def test_consistent_reports_pass_and_remain_read_only(self):
        detail, plan = make_reports()

        result = audit_reports(detail, plan)

        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["read_only"])
        self.assertFalse(result["catalog_mutated"])
        self.assertFalse(result["database_mutated"])
        self.assertFalse(result["migration_gate_allowed"])
        self.assertEqual(result["records_requiring_review"], 2)
        self.assertEqual(result["overlap_between_review_groups"], 0)

    def test_mismatched_product_totals_fail(self):
        detail, plan = make_reports()
        plan["product_count"] = 4

        with self.assertRaisesRegex(ValueError, "Product totals do not match"):
            audit_reports(detail, plan)

    def test_review_group_overlap_fails(self):
        detail, plan = make_reports()
        detail["products_missing_canonical_image"] = group(
            [{"product_id": "p2"}, {"product_id": "p1"}]
        )
        plan["records_requiring_review"] = [
            {"product_id": "p1"},
            {"product_id": "p2"},
        ]
        plan["records_requiring_review_count"] = 2
        plan["review_reasons"]["missing_canonical_image"] = 2

        with self.assertRaisesRegex(ValueError, "overlap"):
            audit_reports(detail, plan)

    def test_open_migration_gate_fails(self):
        detail, plan = make_reports()
        plan["migration_gate"]["allowed"] = True

        with self.assertRaisesRegex(ValueError, "gate must explicitly remain closed"):
            audit_reports(detail, plan)

    def test_automatic_repairs_fail(self):
        detail, plan = make_reports()
        plan["automatic_repairs"] = 1

        with self.assertRaisesRegex(ValueError, "zero automatic repairs"):
            audit_reports(detail, plan)

    def test_duplicate_review_identifiers_fail(self):
        detail, plan = make_reports()
        plan["records_requiring_review"].append({"product_id": "p1"})

        with self.assertRaisesRegex(ValueError, "Duplicate product identifiers"):
            audit_reports(detail, plan)


if __name__ == "__main__":
    unittest.main()
