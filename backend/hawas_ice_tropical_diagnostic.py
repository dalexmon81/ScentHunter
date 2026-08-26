"""
ScentHunter - Hawas Ice vs Hawas Tropical diagnostic

DIAGNOSTIC ONLY.
Does NOT modify main.py, product_matcher.py, scrapers, catalog or index.

It reuses the existing diagnostic_search.py pipeline and extracts only
the raw/matched records whose product name identifies Hawas Ice or
Hawas Tropical. It then compares the two paths field-by-field.

Run from backend/:

    python hawas_ice_tropical_diagnostic.py

Optional:

    python hawas_ice_tropical_diagnostic.py --stores bplatz deloox notino
    python hawas_ice_tropical_diagnostic.py --output hawas_compare.json

The output is written to JSON and also printed as a compact comparison.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
from typing import Any, Dict, List

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)

if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

diagnostic = importlib.import_module("diagnostic_search")


DEFAULT_STORES = [
    "bplatz",
    "deloox",
    "parfumcity",
    "parfumzentrum",
    "perfumemarket",
    "sabina",
    "orioudh",
    "notino",
]

DEFAULT_OUTPUT = os.path.join(
    CURRENT_DIR,
    "hawas_ice_tropical_diagnostic.json",
)


def text(value: Any) -> str:
    return str(value or "").strip()


def norm(value: Any) -> str:
    value = text(value).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def classify(name: str) -> str:
    key = norm(name)
    if "hawas ice" in key:
        return "Hawas Ice"
    if "hawas tropical" in key:
        return "Hawas Tropical"
    return ""


def compact(record: Dict[str, Any]) -> Dict[str, Any]:
    wanted = [
        "store",
        "attempt",
        "raw_index",
        "name",
        "brand",
        "url",
        "price",
        "size_ml",
        "concentration",
        "store_product_id",
        "store_variant_id",
        "gtin",
        "mpn",
        "sku",
        "family_id",
        "family_name",
        "canonical_name",
        "catalog_variant",
        "match_method",
        "current_identity_key",
        "proposed_variant_key",
    ]
    result = {key: record.get(key) for key in wanted}
    result["product_case"] = classify(text(record.get("name")))
    result["target_overlap"] = record.get("target_overlap")
    return result


def extract_candidates(store_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []

    for candidate in store_report.get("all_raw_candidates", []):
        case = classify(text(candidate.get("name")))
        if case:
            found.append(compact(candidate))

    for candidate in store_report.get("matched_candidates", []):
        case = classify(text(candidate.get("name")))
        if case:
            item = compact(candidate)
            item["stage"] = "matched"
            found.append(item)

    for candidate in store_report.get("non_matched_candidates", []):
        case = classify(text(candidate.get("name")))
        if case:
            item = compact(candidate)
            item["stage"] = "non_matched"
            found.append(item)

    return found


def unique_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    output = []

    for record in records:
        key = (
            record.get("store"),
            record.get("attempt"),
            record.get("raw_index"),
            record.get("product_case"),
            record.get("stage"),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(record)

    return output


def compare_records(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    ice = [r for r in records if r["product_case"] == "Hawas Ice"]
    tropical = [r for r in records if r["product_case"] == "Hawas Tropical"]

    fields = [
        "brand",
        "family_id",
        "family_name",
        "canonical_name",
        "catalog_variant",
        "match_method",
        "store_product_id",
        "store_variant_id",
        "gtin",
        "mpn",
        "sku",
        "current_identity_key",
        "proposed_variant_key",
    ]

    ice_values = {
        field: sorted(
            {
                json.dumps(r.get(field), ensure_ascii=False, sort_keys=True)
                for r in ice
            }
        )
        for field in fields
    }

    tropical_values = {
        field: sorted(
            {
                json.dumps(r.get(field), ensure_ascii=False, sort_keys=True)
                for r in tropical
            }
        )
        for field in fields
    }

    differences = []

    for field in fields:
        if ice_values[field] != tropical_values[field]:
            differences.append(
                {
                    "field": field,
                    "ice": ice_values[field],
                    "tropical": tropical_values[field],
                }
            )

    return {
        "hawas_ice_count": len(ice),
        "hawas_tropical_count": len(tropical),
        "ice": ice,
        "tropical": tropical,
        "field_differences": differences,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stores",
        nargs="+",
        default=DEFAULT_STORES,
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
    )
    args = parser.parse_args()

    full_report: Dict[str, Any] = {
        "diagnostic": "Hawas Ice vs Hawas Tropical",
        "query": "Hawas",
        "stores": args.stores,
        "store_reports": [],
        "candidates": [],
    }

    for store in args.stores:
        print(f"[DIAGNOSTIC] {store} ...", flush=True)
        report = diagnostic.run_store(store, "Hawas")
        full_report["store_reports"].append(
            {
                "store": store,
                "status": report.get("status"),
                "raw_total": report.get("raw_total"),
                "errors": report.get("errors", []),
            }
        )
        full_report["candidates"].extend(
            extract_candidates(report)
        )

    full_report["candidates"] = unique_records(
        full_report["candidates"]
    )

    full_report["comparison"] = compare_records(
        full_report["candidates"]
    )

    with open(
        args.output,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            full_report,
            file,
            ensure_ascii=False,
            indent=2,
        )

    comparison = full_report["comparison"]

    print("\n=== HAWAS ICE vs HAWAS TROPICAL ===")
    print(
        f"Ice records: {comparison['hawas_ice_count']}"
    )
    print(
        f"Tropical records: {comparison['hawas_tropical_count']}"
    )

    print("\n=== DIFFERENZE ===")
    if not comparison["field_differences"]:
        print("Nessuna differenza nei campi diagnostici.")
    else:
        for difference in comparison["field_differences"]:
            print(f"\n{difference['field']}:")
            print(f"  ICE      = {difference['ice']}")
            print(f"  TROPICAL = {difference['tropical']}")

    print(f"\nReport completo: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
