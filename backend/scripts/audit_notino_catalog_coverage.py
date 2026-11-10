"""Audit Notino core-fragrance brand coverage against the canonical catalog.

Read-only utility. It never writes to the catalog or database.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from backend.gtin import is_valid_gtin
from backend.scripts.build_notino_match_candidates import (
    _brand_key,
    iter_perfume_rows,
)


def audit_coverage(feed_path: str | Path, catalog_path: str | Path,
                   candidates_path: str | Path | None = None) -> list[dict]:
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    canonical_brands: dict[str, set[str]] = defaultdict(set)
    for product in catalog.get("products", []):
        brand = (product.get("brand_name") or "").strip()
        if brand:
            canonical_brands[_brand_key(brand)].add(brand)

    candidate_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    if candidates_path:
        with Path(candidates_path).open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("feed_external_id") and row.get("review_status") == "needs_human_review":
                    candidate_rows[row["feed_external_id"]].append(row)

    grouped: dict[str, dict] = {}
    for row in iter_perfume_rows(feed_path):
        brand = (row.get("brand") or "(missing)").strip()
        key = _brand_key(brand)
        item = grouped.setdefault(key, {
            "feed_brand": brand,
            "normalized_brand_key": key,
            "catalog_brand_present": bool(canonical_brands.get(key)),
            "canonical_brand_names": " | ".join(sorted(canonical_brands.get(key, set()))),
            "feed_products": 0,
            "valid_gtin_products": 0,
            "invalid_gtin_products": 0,
            "candidate_products": 0,
            "strong_variant_candidates": 0,
            "ambiguous_candidates": 0,
            "medium_candidates": 0,
            "low_or_conflict_candidates": 0,
            "no_candidate_products": 0,
            "product_types": Counter(),
        })
        item["feed_products"] += 1
        if is_valid_gtin(row.get("gtin", "")):
            item["valid_gtin_products"] += 1
        else:
            item["invalid_gtin_products"] += 1
        terminal = row.get("product_type", "").split(">")[-1].strip()
        item["product_types"][terminal] += 1
        matches = candidate_rows.get(row.get("id", ""), [])
        if not matches:
            item["no_candidate_products"] += 1
            continue
        item["candidate_products"] += 1
        top = matches[0]
        band = top.get("confidence_band", "")
        scope = top.get("candidate_scope", "")
        if band == "review_high" and scope == "variant":
            item["strong_variant_candidates"] += 1
        elif band == "ambiguous":
            item["ambiguous_candidates"] += 1
        elif band == "review_medium":
            item["medium_candidates"] += 1
        else:
            item["low_or_conflict_candidates"] += 1

    output = []
    for item in grouped.values():
        item["catalog_coverage_status"] = (
            "brand_present_name_or_variant_gap" if item["catalog_brand_present"]
            else "brand_not_in_catalog"
        )
        item["product_types"] = " | ".join(
            f"{name}: {count}" for name, count in sorted(item["product_types"].items())
        )
        item["candidate_rate"] = round(item["candidate_products"] / item["feed_products"], 4)
        output.append(item)
    return sorted(output, key=lambda x: (-x["feed_products"], x["feed_brand"].casefold()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feed", type=Path)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--csv", type=Path, default=Path("notino-brand-coverage.csv"))
    parser.add_argument("--json", type=Path, default=Path("notino-brand-coverage.json"))
    args = parser.parse_args()
    rows = audit_coverage(args.feed, args.catalog, args.candidates)
    fields = [
        "feed_brand", "normalized_brand_key", "catalog_coverage_status",
        "catalog_brand_present", "canonical_brand_names", "feed_products",
        "valid_gtin_products", "invalid_gtin_products", "candidate_products",
        "candidate_rate", "strong_variant_candidates", "ambiguous_candidates",
        "medium_candidates", "low_or_conflict_candidates", "no_candidate_products",
        "product_types",
    ]
    with args.csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    totals = {
        "feed_brands": len(rows),
        "brands_present_in_catalog": sum(r["catalog_brand_present"] for r in rows),
        "brands_absent_from_catalog": sum(not r["catalog_brand_present"] for r in rows),
        "feed_products": sum(r["feed_products"] for r in rows),
        "products_from_brands_absent_from_catalog": sum(r["feed_products"] for r in rows if not r["catalog_brand_present"]),
        "products_from_brands_present_in_catalog": sum(r["feed_products"] for r in rows if r["catalog_brand_present"]),
        "candidate_products": sum(r["candidate_products"] for r in rows),
        "no_candidate_products": sum(r["no_candidate_products"] for r in rows),
        "candidate_file_used": str(args.candidates) if args.candidates else None,
        "csv": str(args.csv),
    }
    args.json.write_text(json.dumps({"summary": totals, "brands": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(totals, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
