from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import traceback
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import main as scent_main

DEFAULT_OUTPUT = os.path.join(CURRENT_DIR, "discovery_coverage_report.json")


def text(value: Any) -> str:
    return str(value or "").strip()


def norm(value: Any) -> str:
    return scent_main.norm(value)


def field(item: Dict[str, Any], *keys: str) -> Any:
    return scent_main.product_field(item, *keys)


def identity(item: Dict[str, Any]) -> Tuple[Any, ...]:
    try:
        return tuple(scent_main.product_identity_key(item))
    except Exception:
        return (
            norm(field(item, "brand", "source_brand")),
            norm(field(item, "name", "title", "product_name")),
            text(item.get("url")).lower(),
        )


def candidate_summary(
    item: Dict[str, Any],
    store: str,
    attempt: str,
    raw_index: int,
) -> Dict[str, Any]:
    return {
        "store": store,
        "attempt": attempt,
        "raw_index": raw_index,
        "name": text(field(item, "name", "title", "product_name")),
        "brand": text(field(item, "brand", "source_brand")),
        "url": text(item.get("url")),
        "size_ml": scent_main.product_size_ml(item),
        "concentration": text(scent_main.product_concentration(item)),
        "gender": text(scent_main.product_gender(item))
        if hasattr(scent_main, "product_gender")
        else "",
        "store_product_id": text(
            scent_main.identity_value(
                item, "store_product_id", "product_id", "catalog_id"
            )
        ),
        "store_variant_id": text(
            scent_main.identity_value(item, "store_variant_id", "variant_id")
        ),
        "gtin": text(
            scent_main.identity_value(
                item, "gtin", "ean", "ean13", "barcode", "upc"
            )
        ),
        "mpn": text(
            scent_main.identity_value(
                item, "mpn", "manufacturer_part_number", "manufacturerNumber"
            )
        ),
        "sku": text(scent_main.identity_value(item, "sku")),
        "available": item.get("available"),
        "availability": text(scent_main.product_availability(item)),
        "family_id": text(item.get("family_id")),
        "canonical_name": text(item.get("canonical_name")),
        "catalog_variant": text(item.get("catalog_variant")),
        "match_method": text(item.get("match_method")),
    }


def resolve_catalog(item: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    try:
        result = scent_main._catalog_match(item, query)
    except Exception:
        return None
    return result if isinstance(result, dict) else None


def variant_key(item: Dict[str, Any], query: str) -> Tuple[str, str, str, str]:
    canonical = text(
        item.get("canonical_name")
        or item.get("catalog_variant")
        or field(item, "name", "title", "product_name")
    )
    brand = text(
        item.get("canonical_brand")
        or item.get("brand")
        or item.get("source_brand")
    )
    size = scent_main.product_size_ml(item)
    concentration = text(scent_main.product_concentration(item))
    gender = text(scent_main.product_gender(item)) if hasattr(
        scent_main, "product_gender"
    ) else ""

    # Prefer the Registry identity when available. Otherwise use the raw
    # normalized product identity. This is diagnostic grouping only.
    family_id = text(item.get("family_id"))
    if family_id and canonical:
        return (
            family_id,
            norm(canonical),
            text(size),
            norm(" ".join((concentration, gender))),
        )

    return (
        norm(brand),
        norm(canonical),
        text(size),
        norm(" ".join((concentration, gender))),
    )


def run_store(store: str, query: str) -> Dict[str, Any]:
    attempts = scent_main.build_search_attempts(store, query)
    report: Dict[str, Any] = {
        "store": store,
        "attempts": attempts,
        "status": "ok",
        "raw_total": 0,
        "raw_by_attempt": [],
        "raw_candidates": [],
        "unique_candidates": [],
        "matched_candidates": [],
        "pipeline_losses": [],
        "errors": [],
    }

    try:
        module = importlib.import_module(f"scrapers.{store}.scraper")
        search_fn = getattr(module, "search", None)
        if not callable(search_fn):
            search_fn = getattr(module, "scrape", None)
        if not callable(search_fn):
            raise RuntimeError(f"{store}: scraper senza search()/scrape()")
    except Exception as exc:
        report["status"] = "error"
        report["errors"].append({
            "stage": "load_scraper",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })
        return report

    raw = []

    for attempt in attempts:
        try:
            results = search_fn(attempt)
        except Exception as exc:
            report["errors"].append({
                "stage": "scraper_attempt",
                "attempt": attempt,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            })
            report["raw_by_attempt"].append({
                "attempt": attempt,
                "count": 0,
                "status": "error",
            })
            continue

        if not isinstance(results, list):
            report["errors"].append({
                "stage": "invalid_response",
                "attempt": attempt,
                "response_type": type(results).__name__,
            })
            report["raw_by_attempt"].append({
                "attempt": attempt,
                "count": 0,
                "status": "invalid_response",
            })
            continue

        report["raw_total"] += len(results)
        attempt_items = []

        for index, item in enumerate(results):
            if not isinstance(item, dict):
                continue
            product = dict(item)
            product.setdefault("store", store)
            raw.append((attempt, index, product))
            attempt_items.append(candidate_summary(product, store, attempt, index))

        report["raw_by_attempt"].append({
            "attempt": attempt,
            "count": len(results),
            "status": "ok",
            "candidates": attempt_items,
        })

    report["raw_candidates"] = [
        candidate_summary(item, store, attempt, index)
        for attempt, index, item in raw
    ]

    seen: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for attempt, index, item in raw:
        key = identity(item)
        if key in seen:
            continue
        summary = candidate_summary(item, store, attempt, index)
        summary["identity_key"] = list(key)
        seen[key] = summary

    report["unique_candidates"] = list(seen.values())

    for summary in report["unique_candidates"]:
        product = {
            "store": store,
            "name": summary["name"],
            "brand": summary["brand"],
            "url": summary["url"],
            "size_ml": summary["size_ml"],
            "concentration": summary["concentration"],
            "gender": summary["gender"],
            "store_product_id": summary["store_product_id"],
            "store_variant_id": summary["store_variant_id"],
            "gtin": summary["gtin"],
            "mpn": summary["mpn"],
            "sku": summary["sku"],
        }

        try:
            matched = bool(scent_main.matches(product, query))
        except Exception as exc:
            report["errors"].append({
                "stage": "matches",
                "candidate": summary,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            })
            matched = False
            summary["loss_stage"] = "matches_error"

        if matched:
            catalog = resolve_catalog(product, query)
            if catalog:
                summary["family_id"] = text(catalog.get("family_id"))
                summary["canonical_name"] = text(catalog.get("canonical_name"))
                summary["catalog_variant"] = text(catalog.get("catalog_variant"))
                summary["match_method"] = text(catalog.get("match_method"))
            summary["variant_key"] = list(variant_key(summary, query))
            report["matched_candidates"].append(summary)
        else:
            if "loss_stage" not in summary:
                summary["loss_stage"] = "validation"
            report["pipeline_losses"].append(summary)

    report["summary"] = {
        "attempt_count": len(attempts),
        "raw_total": report["raw_total"],
        "unique_total": len(report["unique_candidates"]),
        "matched_total": len(report["matched_candidates"]),
        "pipeline_loss_total": len(report["pipeline_losses"]),
        "error_total": len(report["errors"]),
    }
    return report


def build_cross_store_coverage(
    store_reports: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    buckets: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}

    for store, report in store_reports.items():
        for candidate in report.get("matched_candidates", []):
            key = tuple(candidate.get("variant_key", []))
            if len(key) != 4:
                continue
            bucket = buckets.setdefault(
                key,
                {
                    "variant_key": list(key),
                    "canonical_name": candidate.get("canonical_name")
                    or candidate.get("catalog_variant")
                    or candidate.get("name"),
                    "family_id": candidate.get("family_id", ""),
                    "stores": [],
                    "by_store": {},
                },
            )
            bucket["by_store"][store] = {
                "name": candidate.get("name", ""),
                "brand": candidate.get("brand", ""),
                "url": candidate.get("url", ""),
                "size_ml": candidate.get("size_ml"),
                "concentration": candidate.get("concentration", ""),
                "gender": candidate.get("gender", ""),
            }

    all_stores = sorted(store_reports)
    for bucket in buckets.values():
        bucket["stores"] = sorted(bucket["by_store"])
        bucket["missing_from_comparison"] = [
            store for store in all_stores if store not in bucket["by_store"]
        ]
        bucket["store_count"] = len(bucket["stores"])

    return {
        "all_stores": all_stores,
        "variant_count": len(buckets),
        "variants": list(buckets.values()),
    }


def build_attempt_coverage(
    store_reports: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    result = {}
    for store, report in store_reports.items():
        variant_attempts: Dict[str, set] = defaultdict(set)
        for candidate in report.get("raw_candidates", []):
            key = norm(
                " | ".join(
                    (
                        candidate.get("brand", ""),
                        candidate.get("name", ""),
                        text(candidate.get("size_ml")),
                        candidate.get("concentration", ""),
                        candidate.get("gender", ""),
                    )
                )
            )
            if key:
                variant_attempts[key].add(candidate.get("attempt", ""))

        result[store] = {
            "attempt_count": len(report.get("attempts", [])),
            "attempts": report.get("attempts", []),
            "candidate_attempts": [
                {"candidate_key": key, "attempts": sorted(values)}
                for key, values in variant_attempts.items()
            ],
        }
    return result


def run_query(query: str, stores: Optional[List[str]] = None) -> Dict[str, Any]:
    selected = stores if stores is not None else list(scent_main.STORES)
    reports = {}
    for store in selected:
        reports[store] = run_store(store, query)

    coverage = build_cross_store_coverage(reports)

    # A comparative gap is only reported when the same normalized variant
    # was actually observed in at least two stores. It is not treated as
    # proof that the absent store's website contains that product.
    comparative_gaps = [
        variant
        for variant in coverage["variants"]
        if variant["store_count"] >= 2
        and variant["missing_from_comparison"]
    ]

    return {
        "diagnostic": "discovery_coverage",
        "query": query,
        "stores": reports,
        "cross_store_coverage": coverage,
        "comparative_gaps": comparative_gaps,
        "attempt_coverage": build_attempt_coverage(reports),
        "global_summary": {
            "store_count": len(reports),
            "stores_with_errors": [
                store
                for store, report in reports.items()
                if report.get("errors")
            ],
            "total_raw": sum(
                report["summary"]["raw_total"] for report in reports.values()
            ),
            "total_unique": sum(
                report["summary"]["unique_total"] for report in reports.values()
            ),
            "total_matched": sum(
                report["summary"]["matched_total"] for report in reports.values()
            ),
            "total_pipeline_losses": sum(
                report["summary"]["pipeline_loss_total"]
                for report in reports.values()
            ),
            "comparative_gap_count": len(comparative_gaps),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--stores", nargs="+")
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    report = run_query(args.query, args.stores)

    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    if args.json_only:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print(f"Query: {args.query}")
    print("=" * 72)
    for store, data in report["stores"].items():
        summary = data["summary"]
        print(
            f"{store:20} raw={summary['raw_total']:3} "
            f"unique={summary['unique_total']:3} "
            f"matched={summary['matched_total']:3} "
            f"lost={summary['pipeline_loss_total']:3} "
            f"errors={summary['error_total']:2}"
        )

    print()
    print("Comparative gaps:")
    for gap in report["comparative_gaps"]:
        print(
            f"- {gap['canonical_name']} | "
            f"present={', '.join(gap['stores'])} | "
            f"absent={', '.join(gap['missing_from_comparison'])}"
        )

    print()
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
