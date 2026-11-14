"""Export core fragrance rows from a NOTINO CJ XML feed to a review CSV.

This is a read-only transformation. It preserves the source product fields,
adds conservative normalization and GTIN check-digit/duplicate flags, and
never writes to the canonical catalog or offers database.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from backend.gtin import is_valid_gtin
from backend.scripts.build_notino_match_candidates import (
    _brand_key, extract_gender, iter_perfume_rows, strip_product_noise,
)


FIELDS = [
    "id", "title", "brand", "normalized_brand", "normalized_title",
    "gtin", "gtin_valid", "gtin_duplicate_count", "price", "sale_price",
    "availability", "size", "product_type", "gender", "item_group_id",
    "link", "last_updated",
]


def export_core_feed(feed_path: str | Path) -> tuple[list[dict], dict]:
    source_rows = list(iter_perfume_rows(feed_path))
    gtin_counts = Counter(str(row.get("gtin") or "").strip() for row in source_rows)
    output = []
    for source in source_rows:
        gtin = str(source.get("gtin") or "").strip()
        brand = str(source.get("brand") or "").strip()
        title = str(source.get("title") or "").strip()
        output.append({
            "id": str(source.get("id") or "").strip(),
            "title": title,
            "brand": brand,
            "normalized_brand": _brand_key(brand),
            "normalized_title": strip_product_noise(title),
            "gtin": gtin,
            "gtin_valid": is_valid_gtin(gtin),
            "gtin_duplicate_count": gtin_counts.get(gtin, 0) if gtin else 0,
            "price": source.get("price", ""),
            "sale_price": source.get("sale_price", ""),
            "availability": source.get("availability", ""),
            "size": source.get("size", ""),
            "product_type": source.get("product_type", ""),
            "gender": extract_gender(title) or "",
            "item_group_id": source.get("item_group_id", ""),
            "link": source.get("link", ""),
            "last_updated": source.get("last_updated", ""),
        })

    summary = {
        "core_fragrance_products": len(output),
        "unique_external_ids": len({row["id"] for row in output if row["id"]}),
        "valid_gtin_rows": sum(bool(row["gtin_valid"]) for row in output),
        "invalid_gtin_rows": sum(not row["gtin_valid"] for row in output),
        "duplicate_gtin_rows": sum(row["gtin_duplicate_count"] > 1 for row in output),
        "rows_with_price": sum(bool(row["price"]) for row in output),
        "rows_with_sale_price": sum(bool(row["sale_price"]) for row in output),
        "rows_with_explicit_availability": sum(bool(row["availability"]) for row in output),
        "rows_with_affiliate_url": sum(bool(row["link"]) for row in output),
        "database_writes": 0,
        "catalog_writes": 0,
        "automatic_matches": 0,
    }
    return output, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feed", type=Path, help="Path to the extracted CJ XML feed")
    parser.add_argument("--csv", type=Path, default=Path("notino-core-fragrances.csv"))
    parser.add_argument("--json", type=Path, default=Path("notino-core-fragrances.json"))
    args = parser.parse_args()

    rows, summary = export_core_feed(args.feed)
    with args.csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary["csv"] = str(args.csv)
    args.json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
