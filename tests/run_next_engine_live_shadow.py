"""Manual, bounded, read-only live-offer shadow comparison.

Uses the existing Deloox and Sabina scraper adapters for one fixed query.
The same flattened retailer rows are evaluated by the legacy matcher and the
isolated next engine. No production search, database access, or catalog writes.
"""
from __future__ import annotations

import json
import re
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
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    return " ".join(str(value).split())


def _nested_value(row, *path):
    value = row
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    if isinstance(value, dict):
        return value.get("value")
    return value


def _price_number(value):
    if isinstance(value, (int, float)):
        return value
    raw = _text(value).replace("€", "").replace("EUR", "").replace(" ", "")
    if not raw:
        return None
    # Retailer adapters may emit e.g. "34,95 €"; normalize decimal comma.
    raw = raw.replace(".", "").replace(",", ".") if re.search(r",\d{1,2}$", raw) else raw
    try:
        return float(raw)
    except ValueError:
        return None


def _flatten(raw, retailer):
    """Map known scraper output fields without guessing missing identity data."""
    row = dict(raw)
    row["store"] = retailer
    row["name"] = _text(raw.get("name") or raw.get("title") or raw.get("product_name"))
    row["brand"] = _text(raw.get("brand") or _nested_value(raw, "product", "brand"))
    row["url"] = _text(raw.get("url") or raw.get("product_url") or _nested_value(raw, "raw_data", "product_url"))
    row["size_ml"] = (
        raw.get("size_ml")
        or _nested_value(raw, "attributes", "size_ml")
        or _nested_value(raw, "attributes", "volume_ml")
    )
    if row["size_ml"] is None:
        # Do not infer size from a title; the next engine deliberately requires
        # explicit size fields. The legacy matcher can still inspect the title.
        row["size_ml"] = None
    offer = raw.get("offer") if isinstance(raw.get("offer"), dict) else {}
    row["price"] = _price_number(offer.get("price", raw.get("price")))
    row["currency"] = _text(offer.get("currency") or raw.get("currency") or "EUR") or "EUR"
    row["availability"] = offer.get("availability", raw.get("availability", raw.get("available")))
    identity = raw.get("identity") if isinstance(raw.get("identity"), dict) else {}
    for key in ("sku", "gtin", "mpn", "store_product_id"):
        value = identity.get(key)
        if isinstance(value, dict):
            value = value.get("value")
        if value:
            row.setdefault("retailer_product_id", _text(value))
            break
    # Normalize the next engine's explicit aliases while retaining original data.
    row["raw_name"] = row["name"]
    row["brand_raw"] = row["brand"]
    row["product_url"] = row["url"]
    return row


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
    for retailer, module in (("Deloox", deloox), ("Sabina", sabina)):
        try:
            rows = module.search(QUERY)
            source_results[retailer] = [
                _flatten(row, retailer) for row in (rows or [])
                if isinstance(row, dict)
            ][:MAX_PER_RETAILER]
        except Exception as exc:
            source_results[retailer] = []
            errors[retailer] = type(exc).__name__

    records = [row for rows in source_results.values() for row in rows]
    legacy_rows = []
    for index, record in enumerate(records):
        query = " ".join(filter(None, (
            _text(record.get("brand")),
            _text(record.get("name")),
            _text(record.get("size_ml")),
        ))) or QUERY
        try:
            old = legacy.match(record, query=query)
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
            "retailer": record["store"],
            "raw_name": record["name"],
            "brand": record["brand"],
            "size_ml": record.get("size_ml"),
            "price": record.get("price"),
            "url": record.get("url"),
            "legacy": summary,
        })

    next_rows = []
    next_counts = {}
    for retailer, rows in source_results.items():
        result = next_engine.process_records(rows, retailer=retailer)
        next_counts[retailer] = _status_counts(result)
        for group in result.groups:
            for offer in group.offers:
                next_rows.append({
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
        next_rows.extend({
            "retailer": item.offer.retailer,
            "raw_name": item.offer.raw_name,
            "brand": item.offer.brand_raw,
            "size_ml": item.offer.size_ml,
            "price": str(item.offer.price) if item.offer.price is not None else None,
            "url": item.offer.product_url,
            "next": {"status": "unresolved", "reason": item.reason},
        } for item in result.unresolved)
        next_rows.extend({
            "retailer": item.offer.retailer,
            "raw_name": item.offer.raw_name,
            "brand": item.offer.brand_raw,
            "size_ml": item.offer.size_ml,
            "price": str(item.offer.price) if item.offer.price is not None else None,
            "url": item.offer.product_url,
            "next": {"status": "ambiguous", "candidate_product_ids": list(item.candidate_product_ids)},
        } for item in result.ambiguous)

    status = "completed_with_live_rows" if records else "no_live_rows"
    report = {
        "mode": "manual bounded live retailer shadow comparison",
        "query": QUERY,
        "source": "existing Deloox and Sabina scraper search() functions",
        "live_network_requests_attempted": True,
        "production_search_called": False,
        "database_accessed": False,
        "catalog_modified": False,
        "status": status,
        "rows_by_retailer": {key: len(value) for key, value in source_results.items()},
        "input_row_count": len(records),
        "legacy_status_counts": dict(Counter(row["legacy"]["status"] for row in legacy_rows)),
        "next_status_counts_by_retailer": next_counts,
        "scraper_exception_types": errors,
        "legacy_rows": legacy_rows,
        "next_rows": next_rows,
        "interpretation": (
            "Rows come from current retailer scraper responses. Agreement is diagnostic, "
            "not ground-truth accuracy; retailer pages and canonical identities still need review."
        ) if records else "No live offer rows were returned; matcher quality cannot be compared.",
        "elapsed_sec": round(time.monotonic() - started, 3),
    }

    if CATALOG_PATH.read_bytes() != catalog_before:
        raise AssertionError("Canonical catalog changed during live shadow comparison")
    if FAMILY_PATH.read_bytes() != family_before:
        raise AssertionError("Family registry changed during live shadow comparison")
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"legacy_rows", "next_rows"}}, ensure_ascii=False, indent=2))
    if status == "no_live_rows":
        raise SystemExit("No live retailer rows; report artifact was written for diagnosis.")


if __name__ == "__main__":
    main()
