"""Read-only canonical identity audit for duplicate and incomplete catalog records.

Findings are review signals, not automatic corrections. The audit never edits catalog data.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any


def normalize(value: Any) -> str:
    if value is None:
        return ""
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.casefold())).strip()


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def build_identity_audit(raw: dict[str, Any]) -> dict[str, Any]:
    products = raw.get("products")
    variants = raw.get("variants")
    if not isinstance(products, list) or not isinstance(variants, list):
        raise ValueError("Catalog must contain products and variants arrays")

    rows = [p for p in products if isinstance(p, dict)]
    variant_rows = [v for v in variants if isinstance(v, dict)]
    variants_by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    variant_ids: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sizes_by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for v in variant_rows:
        pid = _text(v.get("product_id"))
        if pid:
            variants_by_product[pid].append(v)
        vid = _text(v.get("variant_id"))
        if vid:
            variant_ids[vid].append(v)
        if pid and v.get("size_ml") is not None:
            sizes_by_product[pid].append(v)

    def grouped(key_fn):
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for p in rows:
            key = key_fn(p)
            if key:
                groups[key].append(p)
        return groups

    def summary(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{
            "product_id": p.get("product_id"),
            "brand_name": p.get("brand_name"),
            "canonical_name": p.get("canonical_name") or p.get("name"),
            "concentration": p.get("concentration"),
            "variant_sizes_ml": sorted({
                v.get("size_ml") for v in variants_by_product.get(_text(p.get("product_id")), [])
                if isinstance(v.get("size_ml"), (int, float)) and not isinstance(v.get("size_ml"), bool)
            }),
            "variant_count": len(variants_by_product.get(_text(p.get("product_id")), [])),
        } for p in group]

    same_name = grouped(lambda p: "|".join((
        normalize(p.get("brand_name") or p.get("brand_id")),
        normalize(p.get("canonical_name") or p.get("name")),
    )) if normalize(p.get("brand_name") or p.get("brand_id")) and normalize(p.get("canonical_name") or p.get("name")) else "")
    same_identity = grouped(lambda p: "|".join((
        normalize(p.get("brand_name") or p.get("brand_id")),
        normalize(p.get("canonical_name") or p.get("name")),
        normalize(p.get("concentration")),
    )) if normalize(p.get("brand_name") or p.get("brand_id")) and normalize(p.get("canonical_name") or p.get("name")) else "")

    duplicate_names = [
        {"normalized_key": key, "products": summary(group)}
        for key, group in sorted(same_name.items()) if len(group) > 1
    ]
    duplicate_identity = [
        {"normalized_key": key, "products": summary(group)}
        for key, group in sorted(same_identity.items()) if len(group) > 1
    ]

    shared_aliases: dict[str, dict[str, Any]] = {}
    alias_owners: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for p in rows:
        pid = _text(p.get("product_id"))
        for alias in p.get("aliases", []) if isinstance(p.get("aliases"), list) else []:
            norm = normalize(alias)
            if norm and pid:
                alias_owners[norm][pid] = p
    for alias, owners in alias_owners.items():
        if len(owners) > 1:
            shared_aliases[alias] = {
                "alias": alias,
                "products": summary(list(owners.values())),
                "severity": "review",
            }

    duplicate_variant_ids = [
        {"variant_id": vid, "records": records}
        for vid, records in sorted(variant_ids.items()) if len(records) > 1
    ]
    duplicate_product_sizes = []
    for pid, group in sorted(sizes_by_product.items()):
        sizes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for v in group:
            size = v.get("size_ml")
            if isinstance(size, (int, float)) and not isinstance(size, bool):
                sizes[str(size)].append(v)
        for size, records in sizes.items():
            if len(records) > 1:
                duplicate_product_sizes.append({
                    "product_id": pid, "size_ml": size,
                    "variant_ids": [v.get("variant_id") for v in records],
                    "severity": "review",
                })

    no_variants = [
        {"product_id": p.get("product_id"), "brand_name": p.get("brand_name"),
         "canonical_name": p.get("canonical_name") or p.get("name"),
         "severity": "review"}
        for p in rows if not variants_by_product.get(_text(p.get("product_id")))
    ]
    missing_images = [
        {"product_id": p.get("product_id"), "canonical_name": p.get("canonical_name") or p.get("name"),
         "canonical_image": p.get("canonical_image_url") or p.get("canonical_image") or p.get("image_url"), "severity": "review"}
        for p in rows if not _text(p.get("canonical_image") or p.get("image_url"))
    ]

    return {
        "status": "complete",
        "read_only": True,
        "catalog_mutated": False,
        "product_count": len(rows),
        "variant_count": len(variant_rows),
        "duplicate_normalized_brand_name": {"count": len(duplicate_names), "items": duplicate_names},
        "duplicate_normalized_brand_name_concentration": {"count": len(duplicate_identity), "items": duplicate_identity},
        "shared_product_aliases": {"count": len(shared_aliases), "items": list(shared_aliases.values())},
        "duplicate_variant_ids": {"count": len(duplicate_variant_ids), "items": duplicate_variant_ids},
        "duplicate_sizes_within_product": {"count": len(duplicate_product_sizes), "items": duplicate_product_sizes},
        "products_without_variants": {"count": len(no_variants), "items": no_variants},
        "products_missing_image": {"count": len(missing_images), "items": missing_images},
        "policy": "Findings are diagnostic review signals. No product, variant, alias, image, or catalog data is modified.",
    }


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    catalog = root / "backend" / "product_catalog.json"
    output = root / "catalog-identity-audit.json"
    try:
        with catalog.open("r", encoding="utf-8") as handle:
            report = build_identity_audit(json.load(handle))
        report["catalog_path"] = "backend/product_catalog.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({
        "status": report["status"], "read_only": True,
        "product_count": report["product_count"], "variant_count": report["variant_count"],
        "duplicate_normalized_brand_name": report["duplicate_normalized_brand_name"]["count"],
        "duplicate_normalized_brand_name_concentration": report["duplicate_normalized_brand_name_concentration"]["count"],
        "shared_product_aliases": report["shared_product_aliases"]["count"],
        "duplicate_variant_ids": report["duplicate_variant_ids"]["count"],
        "duplicate_sizes_within_product": report["duplicate_sizes_within_product"]["count"],
        "products_without_variants": report["products_without_variants"]["count"],
        "products_missing_image": report["products_missing_image"]["count"],
        "report_file": "catalog-identity-audit.json",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
