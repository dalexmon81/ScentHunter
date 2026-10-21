"""Detailed, read-only catalog classification with a complete JSON report artifact."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def _label(value: Any, fallback: str = "(missing)") -> str:
    if value is None or not str(value).strip():
        return fallback
    return str(value).strip()


def build_detail_report(raw: dict[str, Any]) -> dict[str, Any]:
    products = raw.get("products")
    variants = raw.get("variants")
    if not isinstance(products, list) or not isinstance(variants, list):
        raise ValueError("Catalog must contain products and variants arrays")

    product_rows = [row for row in products if isinstance(row, dict)]
    variant_rows = [row for row in variants if isinstance(row, dict)]
    product_ids = {
        str(row.get("product_id")).strip()
        for row in product_rows
        if row.get("product_id") is not None and str(row.get("product_id")).strip()
    }
    variants_by_product: dict[str, list[dict[str, Any]]] = {}
    orphan_variant_rows: list[dict[str, Any]] = []
    for row in variant_rows:
        pid = _label(row.get("product_id"), "")
        if not pid or pid not in product_ids:
            orphan_variant_rows.append({
                "variant_id": row.get("variant_id"),
                "product_id": row.get("product_id"),
            })
        else:
            variants_by_product.setdefault(pid, []).append(row)

    without_variants: list[dict[str, Any]] = []
    missing_images: list[dict[str, Any]] = []
    missing_names: list[dict[str, Any]] = []
    missing_brands: list[dict[str, Any]] = []
    for row in product_rows:
        pid = _label(row.get("product_id"), "")
        details = {
            "product_id": row.get("product_id"),
            "brand_id": row.get("brand_id"),
            "brand_name": row.get("brand_name"),
            "canonical_name": row.get("canonical_name") or row.get("name"),
            "family_name": row.get("family_name"),
            "source_status": row.get("source_status"),
            "concentration": row.get("concentration"),
            "gender": row.get("gender"),
        }
        if not pid or not variants_by_product.get(pid):
            without_variants.append(details)
        if not _label(row.get("canonical_image") or row.get("image_url"), ""):
            missing_images.append(details)
        if not _label(row.get("canonical_name") or row.get("name"), ""):
            missing_names.append(details)
        if not _label(row.get("brand_name") or row.get("brand_id"), ""):
            missing_brands.append(details)

    def grouped(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
        return dict(sorted(Counter(_label(row.get(field)) for row in rows).items()))

    return {
        "status": "complete",
        "read_only": True,
        "catalog_mutated": False,
        "product_count": len(product_rows),
        "variant_count": len(variant_rows),
        "products_without_variants": {
            "count": len(without_variants),
            "by_family": grouped(without_variants, "family_name"),
            "by_source_status": grouped(without_variants, "source_status"),
            "all_records": without_variants,
        },
        "products_missing_canonical_image": {
            "count": len(missing_images),
            "by_family": grouped(missing_images, "family_name"),
            "by_source_status": grouped(missing_images, "source_status"),
            "all_records": missing_images,
        },
        "products_missing_name": {
            "count": len(missing_names),
            "all_records": missing_names,
        },
        "products_missing_brand": {
            "count": len(missing_brands),
            "all_records": missing_brands,
        },
        "orphan_variants": {
            "count": len(orphan_variant_rows),
            "all_records": orphan_variant_rows,
        },
        "interpretation": (
            "This report groups structural findings for human review. It does not infer "
            "that a product without variants is invalid, does not invent variant IDs, "
            "and does not repair or write catalog/database data."
        ),
    }


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    catalog_path = root / "backend" / "product_catalog.json"
    report_path = root / "catalog-preflight-detail.json"
    try:
        with catalog_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        report = build_detail_report(raw)
        report["catalog_path"] = "backend/product_catalog.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({
        "status": "complete",
        "read_only_catalog": True,
        "report_file": str(report_path.relative_to(root)),
        "product_count": report["product_count"],
        "variant_count": report["variant_count"],
        "products_without_variants": report["products_without_variants"]["count"],
        "products_missing_canonical_image": report["products_missing_canonical_image"]["count"],
        "products_missing_name": report["products_missing_name"]["count"],
        "products_missing_brand": report["products_missing_brand"]["count"],
        "orphan_variants": report["orphan_variants"]["count"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
