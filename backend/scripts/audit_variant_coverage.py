"""Read-only coverage audit for canonical fragrance variants.

The report separates mere variant existence from useful variant completeness:
size and concentration are required for a research-ready variant, while GTIN
coverage is reported separately because not every legitimate product has a
published GTIN. It never creates variants, changes catalog rows, or contacts
retailers.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.db import make_engine


QUERY = text("""
    SELECT b.name AS brand_name,
           f.name AS fragrance_name,
           COUNT(pv.id) AS variant_count,
           COUNT(pv.id) FILTER (WHERE pv.size_ml IS NOT NULL) AS variants_with_size,
           COUNT(pv.id) FILTER (WHERE pv.concentration IS NOT NULL AND trim(pv.concentration) <> '') AS variants_with_concentration,
           COUNT(pv.id) FILTER (WHERE pv.gtin IS NOT NULL AND trim(pv.gtin) <> '') AS variants_with_gtin,
           COUNT(pv.id) FILTER (
               WHERE pv.size_ml IS NOT NULL
                 AND pv.concentration IS NOT NULL
                 AND trim(pv.concentration) <> ''
           ) AS complete_variant_count
      FROM fragrances f
      JOIN brands b ON b.id = f.brand_id
 LEFT JOIN product_variants pv ON pv.fragrance_id = f.id
  GROUP BY b.name, f.name
  ORDER BY b.name, f.name
""")


def _count(row: dict, key: str) -> int:
    return int(row.get(key, 0) or 0)


def build_report(rows: list[dict]) -> dict:
    by_brand: dict[str, dict] = {}
    no_variants: list[dict] = []
    incomplete: list[dict] = []
    total_variants = 0
    variants_with_size = 0
    variants_with_concentration = 0
    variants_with_gtin = 0
    complete_variants = 0

    for row in rows:
        brand = str(row["brand_name"])
        name = str(row["fragrance_name"])
        count = _count(row, "variant_count")
        with_size = _count(row, "variants_with_size")
        with_concentration = _count(row, "variants_with_concentration")
        with_gtin = _count(row, "variants_with_gtin")
        complete = _count(row, "complete_variant_count")
        item = by_brand.setdefault(brand, {
            "brand": brand,
            "fragrances": 0,
            "fragrances_with_variants": 0,
            "fragrances_without_variants": 0,
            "fragrances_with_complete_variants": 0,
            "fragrances_needing_variant_research": 0,
            "variant_rows": 0,
            "variants_with_size": 0,
            "variants_with_concentration": 0,
            "variants_with_gtin": 0,
            "complete_variant_rows": 0,
        })
        item["fragrances"] += 1
        item["variant_rows"] += count
        item["variants_with_size"] += with_size
        item["variants_with_concentration"] += with_concentration
        item["variants_with_gtin"] += with_gtin
        item["complete_variant_rows"] += complete

        total_variants += count
        variants_with_size += with_size
        variants_with_concentration += with_concentration
        variants_with_gtin += with_gtin
        complete_variants += complete

        if count:
            item["fragrances_with_variants"] += 1
        else:
            item["fragrances_without_variants"] += 1
            no_variants.append({"brand": brand, "fragrance": name})

        if complete:
            item["fragrances_with_complete_variants"] += 1
        else:
            item["fragrances_needing_variant_research"] += 1
            incomplete.append({
                "brand": brand,
                "fragrance": name,
                "variant_count": count,
                "variants_missing_size": count - with_size,
                "variants_missing_concentration": count - with_concentration,
                "variants_missing_gtin": count - with_gtin,
            })

    ordered = sorted(by_brand.values(), key=lambda x: x["brand"].casefold())
    total_fragrances = len(rows)
    fragrances_with_variants = total_fragrances - len(no_variants)
    fragrances_with_complete = total_fragrances - len(incomplete)
    return {
        "status": "read_only_variant_coverage_audit",
        "fragrances": total_fragrances,
        "fragrances_with_variants": fragrances_with_variants,
        "fragrances_without_variants": len(no_variants),
        "fragrances_with_complete_variants": fragrances_with_complete,
        "fragrances_needing_variant_research": len(incomplete),
        "variant_rows": total_variants,
        "variants_with_size": variants_with_size,
        "variants_with_concentration": variants_with_concentration,
        "variants_with_gtin": variants_with_gtin,
        "complete_variant_rows": complete_variants,
        "coverage_percent": round(
            fragrances_with_complete * 100 / total_fragrances, 2
        ) if total_fragrances else 0.0,
        "gtin_coverage_percent": round(
            variants_with_gtin * 100 / total_variants, 2
        ) if total_variants else 0.0,
        "by_brand": ordered,
        "missing_variant_research": no_variants,
        "incomplete_variant_research": incomplete,
        "variants_created": 0,
        "retailer_requests_made": 0,
        "database_modified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", dest="csv_path", help="optional path for the incomplete-variant research queue")
    parser.add_argument("--summary-only", action="store_true", help="omit detailed research queues from stdout")
    args = parser.parse_args()
    engine = make_engine()
    try:
        if engine.dialect.name != "postgresql":
            raise SystemExit("STOP: variant coverage audit requires the canonical PostgreSQL database")
        with engine.connect() as connection:
            rows = [dict(row) for row in connection.execute(QUERY).mappings().all()]
        report = build_report(rows)
        printable = dict(report)
        if args.summary_only:
            printable.pop("missing_variant_research", None)
            printable.pop("incomplete_variant_research", None)
        print(json.dumps(printable, ensure_ascii=False, indent=2))
        if args.csv_path:
            path = Path(args.csv_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="") as handle:
                fields = [
                    "brand", "fragrance", "variant_count",
                    "variants_missing_size", "variants_missing_concentration",
                    "variants_missing_gtin",
                ]
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(report["incomplete_variant_research"])
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
