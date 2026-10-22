"""Manual, bounded, read-only live-offer shadow comparison.

Runs the existing Deloox and Sabina scraper adapters for one fixed query, then
feeds the same real retailer rows to the legacy matcher and next engine.
It does not import catalog_engine, access a database, write the catalog, or
trigger a production search/resync. The only output is a CI report artifact.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

from backend.product_matcher import ProductMatcher
from backend.scenthunter_next_engine.next_engine_service import NextEngineService
from backend.scrapers.deloox import scraper as deloox
from backend.scrapers.sabina import scraper as sabina

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "backend" / "product_catalog.json"
FAMILY_PATH = ROOT / "backend" / "family_registry.json"
REPORT_PATH = ROOT / "next-engine-live-shadow-comparison.json"
QUERY = "Liquid Brun"
MAX_PER_RETAILER = 20


def _text(value):
    return " ".join(str(value or "").split())


def _status_counts(result):
    return {
        "matched": result.matched_offer_count,
        "unresolved": len(result.unresolved),
        "ambiguous": len(result.ambiguous),
        "rejected": len(result.rejected_rows),
        "normalized": result.normalized_offer_count,
    }


def main():
    started = time.monotonic()
    catalog_before = CATALOG_PATH.read_bytes()
    family_before = FAMILY_PATH.read_bytes()
    catalog = json.loads(catalog_before.decode("utf-8"))
    family = json.loads(family_before.decode("utf-8"))
    legacy = ProductMatcher(catalog, family)
    next_engine = NextEngineService.from_catalog_file(CATALOG_PATH)

    source_results = {}
    errors = {}
    for retailer, module in (("deloox", deloox), ("sabina", sabina)):
        try:
            rows = module.search(QUERY)
            source_results[retailer] = [
                dict(row) for row in (rows or [])
                if isinstance(row, dict)
            ][:MAX_PER_RETAILER]
        except Exception as exc:
            source_results[retailer] = []
            errors[retailer] = type(exc).__name__

    records = []
    for retailer, rows in source_results.items():
        for row in rows:
            record = dict(row)
            record.setdefault("store", retailer)
            records.append(record)

    if not records:
        report = {
            "mode": "manual bounded live retailer shadow comparison",
            "query": QUERY,
            "source": "existing Deloox and Sabina scraper search() functions",
            "live_network_requests_attempted": True,
            "production_search_called": False,
            "database_accessed": False,
            "catalog_modified": False,
            "status": "no_live_rows",
            "rows_by_retailer": {k: len(v) for k, v in source_results.items()},
            "scraper_exception_types": errors,
            "elapsed_sec": round(time.monotonic() - started, 3),
            "interpretation": "No live offer rows were returned; this run cannot compare matcher quality.",
        }
    else:
        next_result = next_engine.process_records(records, retailer="live-retailer-shadow")
        legacy_rows = []
        for index, record in enumerate(records):
            query = " ".join(filter(None, (
                _text(record.get("brand") or record.get("source_brand")),
                _text(record.get("name") or record.get("title") or record.get("source_name")),
                _text(record.get("size_ml")),
            )))
            try:
                old = legacy.match(record, query=query or QUERY)
                if old is None:
                    summary = {"status": "unmatched"}
                else:
                    summary = {
                        "status": "matched",
                        "canonical_name": old.get("canonical_name") or old.get("name"),
                        "product_identity": old.get("product_identity") or old.get("catalog_id"),
                        "variant_id": old.get("variant_id"),
                        "size_ml": old.get("size_ml"),
                        "match_method": old.get("match_method"),
                    }
            except Exception as exc:
                summary = {"status": "error", "error_type": type(exc).__name__}
            legacy_rows.append({
                "index": index,
                "retailer": _text(record.get("store")),
                "raw_name": _text(record.get("name") or record.get("title") or record.get("source_name")),
                "brand": _text(record.get("brand") or record.get("source_brand")),
                "size_ml": record.get("size_ml"),
                "price": record.get("price"),
                "url": _text(record.get("url")),
                "legacy": summary,
            })

        new_rows = []
        for group in next_result.groups:
            for offer in group.offers:
                new_rows.append({
                    "retailer": offer.retailer,
                    "raw_name": offer.raw_name,
                    "brand": offer.brand_raw,
                    "size_ml": offer.size_ml,
                    "price": str(offer.price) if offer.price is not None else None,
                    "url": offer.product_url,
                    "next": {
                        "status": "matched",
                        "product_id": group.canonical_product_id,
                        "variant_id": group.canonical_variant_id,
                    },
                })
        new_rows.extend({
            "retailer": item.offer.retailer,
            "raw_name": item.offer.raw_name,
            "brand": item.offer.brand_raw,
            "size_ml": item.offer.size_ml,
            "price": str(item.offer.price) if item.offer.price is not None else None,
            "url": item.offer.product_url,
            "next": {"status": "unresolved", "reason": item.reason},
        } for item in next_result.unresolved)
        new_rows.extend({
            "retailer": item.offer.retailer,
            "raw_name": item.offer.raw_name,
            "brand": item.offer.brand_raw,
            "size_ml": item.offer.size_ml,
            "price": str(item.offer.price) if item.offer.price is not None else None,
            "url": item.offer.product_url,
            "next": {"status": "ambiguous", "candidate_product_ids": list(item.candidate_product_ids)},
        } for item in next_result.ambiguous)

        report = {
            "mode": "manual bounded live retailer shadow comparison",
            "query": QUERY,
            "source": "existing Deloox and Sabina scraper search() functions",
            "live_network_requests_attempted": True,
            "production_search_called": False,
            "database_accessed": False,
            "catalog_modified": False,
            "status": "completed_with_live_rows",
            "rows_by_retailer": {k: len(v) for k, v in source_results.items()},
            "input_row_count": len(records),
            "legacy_status_counts": dict(Counter(row["legacy"]["status"] for row in legacy_rows)),
            "next_status_counts": _status_counts(next_result),
            "scraper_exception_types": errors,
            "legacy_rows": legacy_rows,
            "next_rows": new_rows,
            "interpretation": (
                "These are real rows returned by the current retailer scrapers. "
                "Matcher disagreement is diagnostic, not ground-truth accuracy: "
                "each row still needs review against its retailer page and canonical identity."
            ),
            "elapsed_sec": round(time.monotonic() - started, 3),
        }

    if CATALOG_PATH.read_bytes() != catalog_before:
        raise AssertionError("Canonical catalog changed during live shadow comparison")
    if FAMILY_PATH.read_bytes() != family_before:
        raise AssertionError("Family registry changed during live shadow comparison")
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"legacy_rows", "next_rows"}}, ensure_ascii=False, indent=2))
    if report["status"] == "no_live_rows":
        raise SystemExit("No live retailer rows; report artifact was still written for diagnosis.")


if __name__ == "__main__":
    main()
