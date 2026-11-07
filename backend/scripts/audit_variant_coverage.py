"""Read-only coverage audit for canonical fragrance variants.

This report identifies fragrances that still need source-backed size/concentration
research. It never creates variants, changes catalog rows, or contacts retailers.
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
           COUNT(pv.id) AS variant_count
      FROM fragrances f
      JOIN brands b ON b.id = f.brand_id
 LEFT JOIN product_variants pv ON pv.fragrance_id = f.id
  GROUP BY b.name, f.name
  ORDER BY b.name, f.name
""")


def build_report(rows: list[dict]) -> dict:
    by_brand: dict[str, dict] = {}
    missing: list[dict] = []
    total_variants = 0
    for row in rows:
        brand = str(row["brand_name"])
        name = str(row["fragrance_name"])
        count = int(row["variant_count"])
        item = by_brand.setdefault(brand, {
            "brand": brand,
            "fragrances": 0,
            "fragrances_with_variants": 0,
            "fragrances_without_variants": 0,
            "variant_rows": 0,
        })
        item["fragrances"] += 1
        item["variant_rows"] += count
        total_variants += count
        if count:
            item["fragrances_with_variants"] += 1
        else:
            item["fragrances_without_variants"] += 1
            missing.append({"brand": brand, "fragrance": name})
    ordered = sorted(by_brand.values(), key=lambda x: x["brand"].casefold())
    total_fragrances = len(rows)
    covered = total_fragrances - len(missing)
    return {
        "status": "read_only_variant_coverage_audit",
        "fragrances": total_fragrances,
        "fragrances_with_variants": covered,
        "fragrances_without_variants": len(missing),
        "variant_rows": total_variants,
        "coverage_percent": round(covered * 100 / total_fragrances, 2) if total_fragrances else 0.0,
        "by_brand": ordered,
        "missing_variant_research": missing,
        "variants_created": 0,
        "retailer_requests_made": 0,
        "database_modified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", dest="csv_path", help="optional path for the missing-variant research queue")
    parser.add_argument("--summary-only", action="store_true", help="omit the full missing-name list from stdout")
    args = parser.parse_args()
    engine = make_engine()
    try:
        if engine.dialect.name != "postgresql":
            raise SystemExit("STOP: variant coverage audit requires the canonical PostgreSQL database")
        with engine.connect() as connection:
            rows = [dict(row) for row in connection.execute(QUERY).mappings().all()]
        report = build_report(rows)
        printable = {key: value for key, value in report.items() if key != "missing_variant_research"} if args.summary_only else report
        print(json.dumps(printable, ensure_ascii=False, indent=2))
        if args.csv_path:
            path = Path(args.csv_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["brand", "fragrance"])
                writer.writeheader()
                writer.writerows(report["missing_variant_research"])
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
