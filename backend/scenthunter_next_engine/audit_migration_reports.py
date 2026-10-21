"""Read-only consistency audit for ScentHunter migration review reports."""
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
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _group_records(report: dict[str, Any], *keys: str) -> tuple[int, list[dict[str, Any]]]:
    value = _first(report, *keys)
    if not isinstance(value, dict):
        raise ValueError(f"Expected an object in one of these fields: {', '.join(keys)}")
    records = _first(value, "all_records", "records", "items")
    count = value.get("count")
    if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
        raise ValueError(f"{', '.join(keys)} must contain an all_records list of objects")
    if not isinstance(count, int) or isinstance(count, bool) or count != len(records):
        raise ValueError(f"{', '.join(keys)} count does not match its records")
    return count, records


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


def _review_records(plan: dict[str, Any]) -> list[dict[str, Any]]:
    value = _first(plan, "records_requiring_review", "review_records", "records_to_review")
    if isinstance(value, dict):
        value = _first(value, "all_records", "records", "items")
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError("Migration plan must contain a review-record list")
    return value


def audit_reports(detail: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
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

    detail_products, detail_variants = detail.get("product_count"), detail.get("variant_count")
    if not isinstance(detail_products, int) or detail_products != plan.get("product_count"):
        errors.append("Product totals do not match between detail report and plan")
    if not isinstance(detail_variants, int) or detail_variants != plan.get("variant_count"):
        errors.append("Variant totals do not match between detail report and plan")

    no_variant_count, no_variant_records = _group_records(detail, "products_without_variants")
    missing_image_count, missing_image_records = _group_records(detail, "products_missing_canonical_image")
    review_records = _review_records(plan)
    no_variant_ids = _unique_ids(no_variant_records, "products without variants")
    missing_image_ids = _unique_ids(missing_image_records, "products missing canonical images")
    review_ids = _unique_ids(review_records, "records requiring review")

    overlap = no_variant_ids & missing_image_ids
    if overlap:
        errors.append(f"Review categories overlap for {len(overlap)} product identifier(s)")
    if review_ids != (no_variant_ids | missing_image_ids):
        errors.append("Review records do not equal the union of the no-variant and missing-image groups")

    declared_count = _first(plan, "records_requiring_review_count", "review_record_count", "review_count")
    if declared_count is not None and declared_count != len(review_records):
        errors.append("Declared review count does not match the review record list")

    reasons = plan.get("review_reasons")
    if isinstance(reasons, dict):
        expected = {"no_explicit_variant_records": no_variant_count, "missing_canonical_image": missing_image_count}
        for reason, count in expected.items():
            if reason in reasons and reasons[reason] != count:
                errors.append(f"Review reason {reason!r} count does not match its record group")
        total = sum(v for v in reasons.values() if isinstance(v, int) and not isinstance(v, bool))
        if total != len(review_records):
            errors.append("Review reason totals do not match the review record list")

    for field in ("orphan_variants", "products_missing_brand", "products_missing_name"):
        group = detail.get(field)
        if isinstance(group, dict):
            count, records = group.get("count"), group.get("all_records")
            if not isinstance(records, list) or not isinstance(count, int) or count != len(records):
                errors.append(f"Structural group {field} has an inconsistent count")
            elif count:
                errors.append(f"Structural audit reports {field}={count}")

    summary = {
        "status": "passed" if not errors else "failed", "read_only": True,
        "catalog_mutated": False, "database_mutated": False, "migration_gate_allowed": False,
        "product_count": detail_products, "variant_count": detail_variants,
        "products_without_variants": no_variant_count,
        "products_missing_canonical_image": missing_image_count,
        "records_requiring_review": len(review_ids), "overlap_between_review_groups": len(overlap),
        "errors": errors,
    }
    if errors:
        raise ValueError(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit consistency of read-only ScentHunter migration reports.")
    parser.add_argument("--detail", required=True, type=Path, help="Preflight detail JSON")
    parser.add_argument("--plan", required=True, type=Path, help="Migration plan JSON")
    parser.add_argument("--output", type=Path, help="Optional JSON audit summary output")
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
