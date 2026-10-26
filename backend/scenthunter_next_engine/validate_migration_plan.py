"""Validation rules for the read-only catalog migration review plan.

This module validates report consistency only. It does not modify the catalog,
infer variants, create IDs, or approve a migration.
"""
from __future__ import annotations

from typing import Any


def validate_migration_plan(report: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, dict):
        return ["report_not_object"]

    if report.get("status") != "complete":
        errors.append("report_not_complete")
    if report.get("read_only") is not True:
        errors.append("read_only_flag_not_true")
    if report.get("catalog_mutated") is not False:
        errors.append("catalog_mutation_flag_not_false")
    if report.get("database_mutated") is not False:
        errors.append("database_mutation_flag_not_false")
    if report.get("automatic_repairs") != 0:
        errors.append("automatic_repairs_not_zero")

    product_count = report.get("product_count")
    variant_count = report.get("variant_count")
    if not isinstance(product_count, int) or product_count < 0:
        errors.append("invalid_product_count")
    if not isinstance(variant_count, int) or variant_count < 0:
        errors.append("invalid_variant_count")

    no_variants = report.get("products_without_variants")
    missing_images = report.get("products_missing_canonical_image")
    review = report.get("records_requiring_review")

    for label, section in (
        ("products_without_variants", no_variants),
        ("products_missing_canonical_image", missing_images),
        ("records_requiring_review", review),
    ):
        if not isinstance(section, dict):
            errors.append(f"{label}_section_invalid")
            continue
        count = section.get("count")
        records = section.get("records")
        if not isinstance(count, int) or count < 0:
            errors.append(f"{label}_count_invalid")
        if not isinstance(records, list):
            errors.append(f"{label}_records_invalid")
        elif isinstance(count, int) and count != len(records):
            errors.append(f"{label}_count_mismatch")

    if isinstance(no_variants, dict) and isinstance(no_variants.get("records"), list):
        ids = [
            row.get("product_id")
            for row in no_variants["records"]
            if isinstance(row, dict)
        ]
        if len(ids) != len(set(ids)):
            errors.append("duplicate_ids_in_no_variant_records")

    if isinstance(missing_images, dict) and isinstance(missing_images.get("records"), list):
        ids = [
            row.get("product_id")
            for row in missing_images["records"]
            if isinstance(row, dict)
        ]
        if len(ids) != len(set(ids)):
            errors.append("duplicate_ids_in_missing_image_records")

    gate = report.get("migration_gate")
    if not isinstance(gate, dict):
        errors.append("migration_gate_invalid")
    else:
        if gate.get("allowed") is not False:
            errors.append("migration_gate_must_remain_closed")
        reason = gate.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append("migration_gate_reason_missing")

    return errors


def validate_plan_counts(report: dict[str, Any]) -> dict[str, Any]:
    errors = validate_migration_plan(report)
    return {
        "status": "valid" if not errors else "invalid",
        "error_count": len(errors),
        "errors": errors,
        "migration_allowed": False,
        "catalog_mutated": False,
        "database_mutated": False,
    }
