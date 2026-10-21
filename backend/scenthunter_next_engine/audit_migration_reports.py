"""Read-only consistency audit for ScentHunter migration review reports.

This module validates the relationship between the catalog preflight detail and
the generated migration plan. It does not repair data, write to the catalog, or
connect to a database.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    """Return the first present key, supporting known report naming variants."""
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _records(report: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    value = _first(report, *keys)
    if not isinstance(value, list):
        raise ValueError(f"Expected a list in one of these fields: {', '.join(keys)}")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError(f"All records in {', '.join(keys)} must be JSON objects")
    return value


def _record_id(record: dict[str, Any]) -> str:
    value = _first(record, "product_id", "canonical_product_id", "id")
    if value is None or str(value).strip() == "":
        raise ValueError("A report record is missing product_id/canonical_product_id/id")
    return str(value)


def _unique_ids(records: list[dict[str, Any]], label: str) -> set[str]:
    ids = [_record_id(record) for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate product identifiers found in {label}")
    return set(ids)


def audit_reports(detail: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Return an audit summary or raise ValueError for inconsistent reports."""
    errors: list[str] = []

    if plan.get("status") != "complete":
        errors.append("Migration plan status is not complete")
    if plan.get("read_only") is not True:
        errors.append("Migration plan does not explicitly declare read_only=true")
    if plan.get("catalog_mutated") is not False:
        errors.append("Migration plan does not explicitly declare catalog_mutated=false")
    if plan.get("database_mutated") is not False:
        errors.append("Migration plan does not explicitly declare database_mutated=false")
    if plan.get("automatic_repairs") != 0:
        errors.append("Migration plan must report zero automatic repairs")

    gate = plan.get("migration_gate")
    if not isinstance(gate, dict) or gate.get("allowed") is not False:
        errors.append("Migration gate must explicitly remain closed")

    detail_products = _first(detail, "product_count", "products_count")
    detail_variants = _first(detail, "variant_count", "variants_count")
    plan_products = _first(plan, "product_count", "products_count")
    plan_variants = _first(plan, "variant_count", "variants_count")

    if detail_products is None or plan_products is None or detail_products != plan_products:
        errors.append("Product totals do not match between detail report and plan")
    if detail_variants is None or plan_variants is None or detail_variants != plan_variants:
        errors.append("Variant totals do not match between detail report and plan")

    missing_variants = _records(
        detail,
        "products_without_variants",
        "products_missing_variants",
        "records_without_variants",
    )
    missing_images = _records(
        detail,
        "products_missing_canonical_image",
        "products_without_canonical_image",
        "records_missing_canonical_image",
    )
    review_records = _records(
        plan,
        "records_requiring_review",
        "review_records",
        "records_to_review",
    )

    no_variant_ids = _unique_ids(missing_variants, "products without variants")
    missing_image_ids = _unique_ids(missing_images, "products missing canonical images")
    review_ids = _unique_ids(review_records, "records requiring review")

    overlap = no_variant_ids & missing_image_ids
    if overlap:
        errors.append(
            f"Review categories overlap for {len(overlap)} product identifier(s)"
        )

    expected_review_ids = no_variant_ids | missing_image_ids
    if review_ids != expected_review_ids:
        errors.append(
            "Review records do not equal the union of the no-variant and missing-image groups"
        )

    declared_review_count = _first(
        plan, "records_requiring_review_count", "review_record_count", "review_count"
    )
    if declared_review_count is not None and declared_review_count != len(review_records):
        errors.append("Declared review count does not match the review record list")

    reasons = plan.get("review_reasons")
    if isinstance(reasons, dict):
        expected_reasons = {
            "no_explicit_variant_records": len(no_variant_ids),
            "missing_canonical_image": len(missing_image_ids),
        }
        for reason, expected_count in expected_reasons.items():
            if reason in reasons and reasons[reason] != expected_count:
                errors.append(
                    f"Review reason {reason!r} count does not match its record group"
                )
        if sum(value for value in reasons.values() if isinstance(value, int)) != len(review_records):
            errors.append("Review reason totals do not match the review record list")

    structural = _first(detail, "structural_audit", "structure_audit", "audit")
    if isinstance(structural, dict):
        for field in (
            "orphan_variants",
            "products_missing_brand",
            "products_missing_name",
        ):
            value = structural.get(field)
            if value is not None and value != 0:
                errors.append(f"Structural audit reports {field}={value}")

    summary = {
        "status": "passed" if not errors else "failed",
        "read_only": True,
        "catalog_mutated": False,
        "database_mutated": False,
        "migration_gate_allowed": False,
        "product_count": detail_products,
        "variant_count": detail_variants,
        "products_without_variants": len(no_variant_ids),
        "products_missing_canonical_image": len(missing_image_ids),
        "records_requiring_review": len(review_ids),
        "overlap_between_review_groups": len(overlap),
        "errors": errors,
    }
    if errors:
        raise ValueError(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit consistency of read-only ScentHunter migration reports."
    )
    parser.add_argument("--detail", required=True, type=Path, help="Preflight detail JSON")
    parser.add_argument("--plan", required=True, type=Path, help="Migration plan JSON")
    parser.add_argument(
        "--output", type=Path, help="Optional path for the JSON audit summary"
    )
    args = parser.parse_args()

    try:
        summary = audit_reports(_load_json(args.detail), _load_json(args.plan))
    except ValueError as exc:
        print(str(exc))
        return 1

    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        try:
            args.output.write_text(rendered + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"Cannot write audit summary: {exc}")
            return 1
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
