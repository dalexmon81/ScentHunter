"""Read-only audit for an exported NOTINO.fr CJ Shopping XML feed.

This utility never writes to ScentHunter's database and never modifies the feed.
It reports category coverage, GTIN format buckets, duplicate GTINs and brands.
"""
from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path


GTIN_ACCEPTED_LENGTHS = {8, 12, 13, 14}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _entry_values(entry: ET.Element) -> dict[str, str]:
    values: dict[str, str] = {}
    for child in entry:
        name = _local_name(child.tag)
        if child.text:
            values[name] = child.text.strip()
    return values


def _is_perfume(values: dict[str, str]) -> bool:
    category_id = values.get("google_product_category", "")
    category_name = values.get("google_product_category_name", "").casefold()
    return category_id == "479" or "parfums et eaux de cologne" in category_name


def audit_feed(path: str | Path) -> dict:
    totals = Counter()
    gtin_length_counts = Counter()
    brands = Counter()
    gtin_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    missing_fields = Counter()
    invalid_gtins: list[dict[str, str]] = []

    for _, entry in ET.iterparse(str(path), events=("end",)):
        if _local_name(entry.tag) != "entry":
            continue
        totals["entries"] += 1
        values = _entry_values(entry)
        if not _is_perfume(values):
            entry.clear()
            continue

        totals["perfume_entries"] += 1
        for field in ("gtin", "price", "availability", "link"):
            if not values.get(field):
                missing_fields[field] += 1

        gtin = values.get("gtin", "")
        digits_only = bool(re.fullmatch(r"[0-9]+", gtin))
        if digits_only:
            gtin_length_counts[str(len(gtin))] += 1
            if len(gtin) in GTIN_ACCEPTED_LENGTHS:
                totals["accepted_gtin_length"] += 1
                gtin_rows[gtin].append({
                    "id": values.get("id", ""),
                    "title": values.get("title", ""),
                    "brand": values.get("brand", ""),
                })
            else:
                totals["rejected_gtin_length"] += 1
                invalid_gtins.append({
                    "id": values.get("id", ""),
                    "gtin": gtin,
                    "title": values.get("title", ""),
                    "brand": values.get("brand", ""),
                    "reason": f"unsupported GTIN length: {len(gtin)}",
                })
        else:
            totals["rejected_gtin_format"] += 1
            invalid_gtins.append({
                "id": values.get("id", ""),
                "gtin": gtin,
                "title": values.get("title", ""),
                "brand": values.get("brand", ""),
                "reason": "missing or non-numeric GTIN",
            })

        brands[values.get("brand") or "(missing)"] += 1
        if values.get("sale_price"):
            totals["sale_price_entries"] += 1
        if values.get("availability", "").casefold() == "in stock":
            totals["in_stock_entries"] += 1
        if values.get("price"):
            totals["price_entries"] += 1
        if values.get("link"):
            totals["affiliate_url_entries"] += 1
        entry.clear()

    duplicate_gtins = [
        {"gtin": gtin, "count": len(rows), "source_rows": rows}
        for gtin, rows in sorted(gtin_rows.items())
        if len(rows) > 1
    ]
    totals["unique_accepted_gtins"] = len(gtin_rows)
    totals["duplicate_gtin_values"] = len(duplicate_gtins)

    return {
        "summary": dict(totals),
        "gtin_lengths": dict(sorted(gtin_length_counts.items(), key=lambda item: int(item[0]))),
        "missing_fields": dict(missing_fields),
        "duplicate_gtins": duplicate_gtins,
        "invalid_gtins": invalid_gtins,
        "brands": dict(brands.most_common()),
        "policy_note": (
            "Accepted length is a format check only; it does not verify the GTIN "
            "check digit or prove that the identifier belongs to the listed product."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feed", type=Path, help="Path to the extracted CJ XML file")
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()

    report = audit_feed(args.feed)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
