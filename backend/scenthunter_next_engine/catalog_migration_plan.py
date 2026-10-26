"""Read-only migration planning report for the ScentHunter canonical catalog.

This module classifies catalog records for review. It never changes the catalog,
creates variants, writes to a database, or publishes migration output.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def build_migration_plan(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Catalog root must be a JSON object")

    products = raw.get("products")
    variants = raw.get("variants")
    if not isinstance(products, list) or not isinstance(variants, list):
        raise ValueError("Catalog must contain top-level products and variants arrays")

    product_rows = [row for row in products if isinstance(row, dict)]
    variant_rows = [row for row in variants if isinstance(row, dict)]

    product_ids = {_text(row.get("product_id")) for row in product_rows}
    variants_by_product: dict[str, list[dict[str, Any]]] = {}
    for variant in variant_rows:
        product_id = _text(variant.get("product_id"))
        if product_id:
            variants_by_product.setdefault(product_id, []).append(variant)

    no_variant_records = []
    missing_image_records = []
    review_records = []
    for product in product_rows:
        product_id = _text(product.get("product_id"))
        canonical_name = _text(product.get("canonical_name") or product.get("name"))
        brand_name = _text(product.get("brand_name"))
        has_variants = bool(variants_by_product.get(product_id))
        has_image = bool(_text(product.get("canonical_image") or product.get("image_url")))

        record = {
            "product_id": product.get("product_id"),
            "brand_id": product.get("brand_id"),
            "brand_name": product.get("brand_name"),
            "canonical_name": product.get("canonical_name") or product.get("name"),
            "family_name": product.get("family_name"),
            "source_status": product.get("source_status"),
            "concentration": product.get("concentration"),
            "gender": product.get("gender"),
            "variant_count": len(variants_by_product.get(product_id, [])),
            "has_canonical_image": has_image,
        }

        if not has_variants:
            no_variant_records.append(record)
        if not has_image:
            missing_image_records.append(record)

        blockers = []
        if not product_id:
            blockers.append("missing_product_id")
        if not canonical_name:
            blockers.append("missing_canonical_name")
        if not brand_name:
            blockers.append("missing_brand_name")
        if not has_variants:
            blockers.append("no_explicit_variant_records")
        if not has_image:
            blockers.append("missing_canonical_image")

        # This is a review classification only, never a recommendation to
        # create a variant or infer a size from a product name.
        if blockers:
            record_with_blockers = dict(record)
            record_with_blockers["review_reasons"] = blockers
            review_records.append(record_with_blockers)

    source_status_counts = Counter(
        _text(row.get("source_status")) or "(missing)"
        for row in no_variant_records
    )
    no_variant_brand_counts = Counter(
        _text(row.get("brand_name")) or "(missing)"
        for row in no_variant_records
    )
    missing_image_brand_counts = Counter(
        _text(row.get("brand_name")) or "(missing)"
        for row in missing_image_records
    )

    return {
        "status": "complete",
        "read_only": True,
        "catalog_mutated": False,
        "database_mutated": False,
        "automatic_repairs": 0,
        "product_count": len(product_rows),
        "variant_count": len(variant_rows),
        "products_without_variants": {
            "count": len(no_variant_records),
            "by_source_status": dict(sorted(source_status_counts.items())),
            "by_brand": dict(sorted(no_variant_brand_counts.items())),
            "records": no_variant_records,
        },
        "products_missing_canonical_image": {
            "count": len(missing_image_records),
            "by_brand": dict(sorted(missing_image_brand_counts.items())),
            "records": missing_image_records,
        },
        "records_requiring_review": {
            "count": len(review_records),
            "records": review_records,
        },
        "migration_gate": {
            "allowed": False,
            "reason": (
                "This report is classification only. Do not migrate, generate variant IDs, "
                "or publish changes until missing variants and canonical images have been "
                "resolved through an explicit, reviewable source of truth."
            ),
        },
    }


def main() -> int:
    repository_root = Path(__file__).resolve().parents[2]
    catalog_path = repository_root / "backend" / "product_catalog.json"
    report_path = repository_root / "catalog-migration-plan.json"

    try:
        with catalog_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        report = build_migration_plan(raw)
        report["catalog_path"] = "backend/product_catalog.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps({
        "status": report["status"],
        "read_only": report["read_only"],
        "catalog_mutated": report["catalog_mutated"],
        "database_mutated": report["database_mutated"],
        "product_count": report["product_count"],
        "variant_count": report["variant_count"],
        "products_without_variants": report["products_without_variants"]["count"],
        "products_missing_canonical_image": report["products_missing_canonical_image"]["count"],
        "records_requiring_review": report["records_requiring_review"]["count"],
        "report_file": "catalog-migration-plan.json",
        "migration_allowed": report["migration_gate"]["allowed"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
