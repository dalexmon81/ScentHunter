"""Read-only structural preflight for the canonical ScentHunter catalog.

This module audits raw catalog JSON without writing files, databases, or catalog
records. It reports structural risks for human review; it never repairs data.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any


def _records(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def audit_catalog_data(raw: Any) -> dict[str, Any]:
    """Return deterministic counts and integrity findings for a catalog object."""
    if not isinstance(raw, Mapping):
        raise ValueError("catalog root must be a JSON object")

    product_rows = _records(raw.get("products"))
    variant_rows = _records(raw.get("variants"))
    if not isinstance(raw.get("products"), list):
        raise ValueError("catalog products must be an array")
    if not isinstance(raw.get("variants"), list):
        raise ValueError("catalog variants must be an array")

    product_ids = [row.get("product_id") for row in product_rows]
    variant_ids = [row.get("variant_id") for row in variant_rows]
    valid_product_ids = {value for value in product_ids if _nonempty(value)}
    valid_variant_ids = {value for value in variant_ids if _nonempty(value)}

    duplicate_products = sorted(
        value for value, count in Counter(
            value for value in product_ids if _nonempty(value)
        ).items() if count > 1
    )
    duplicate_variants = sorted(
        value for value, count in Counter(
            value for value in variant_ids if _nonempty(value)
        ).items() if count > 1
    )

    missing_product_id_count = sum(not _nonempty(row.get("product_id")) for row in product_rows)
    missing_variant_id_count = sum(not _nonempty(row.get("variant_id")) for row in variant_rows)
    orphan_variant_count = sum(
        not _nonempty(row.get("product_id")) or row.get("product_id") not in valid_product_ids
        for row in variant_rows
    )
    product_variant_counts = Counter(
        row.get("product_id") for row in variant_rows
        if _nonempty(row.get("product_id")) and row.get("product_id") in valid_product_ids
    )
    products_without_variants = sum(
        _nonempty(row.get("product_id")) and row.get("product_id") not in product_variant_counts
        for row in product_rows
    )
    missing_name_count = sum(
        not _nonempty(row.get("canonical_name")) and not _nonempty(row.get("name"))
        for row in product_rows
    )
    missing_brand_count = sum(
        not _nonempty(row.get("brand_name")) and not _nonempty(row.get("brand_id"))
        for row in product_rows
    )
    missing_size_count = sum(
        row.get("size_ml") is None or isinstance(row.get("size_ml"), bool)
        or not str(row.get("size_ml")).strip()
        for row in variant_rows
    )
    missing_image_count = sum(
        not _nonempty(row.get("canonical_image") or row.get("image_url"))
        for row in product_rows
    )

    findings = []
    checks = [
        ("duplicate_product_ids", len(duplicate_products)),
        ("duplicate_variant_ids", len(duplicate_variants)),
        ("products_missing_id", missing_product_id_count),
        ("variants_missing_id", missing_variant_id_count),
        ("orphan_variants", orphan_variant_count),
        ("products_without_variants", products_without_variants),
        ("products_missing_name", missing_name_count),
        ("products_missing_brand", missing_brand_count),
        ("variants_missing_size", missing_size_count),
        ("products_missing_canonical_image", missing_image_count),
    ]
    for code, count in checks:
        if count:
            findings.append({"code": code, "count": count})

    return {
        "schema_version": raw.get("schema_version"),
        "product_count": len(product_rows),
        "variant_count": len(variant_rows),
        "non_mapping_product_rows": len(raw.get("products", [])) - len(product_rows),
        "non_mapping_variant_rows": len(raw.get("variants", [])) - len(variant_rows),
        "duplicate_product_ids": duplicate_products,
        "duplicate_variant_ids": duplicate_variants,
        "products_without_variants": products_without_variants,
        "orphan_variants": orphan_variant_count,
        "findings": findings,
        "safe_to_consider_migration": not findings and bool(product_rows),
        "read_only": True,
        "automatic_repairs": 0,
    }
