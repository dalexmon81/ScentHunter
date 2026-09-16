#!/usr/bin/env python3
"""
ScentHunter - Liquid Brun pipeline diagnostic.

IMPORTANT:
- Diagnostic only. It does NOT modify backend/main.py.
- It does NOT expose a new HTTP endpoint.
- It does NOT change scraper, ProductMatcher, family_registry or frontend.
- It executes each store independently and reports where candidates disappear.

Usage:
    python backend/diagnose_liquid_brun.py
    python backend/diagnose_liquid_brun.py "Liquid Brun"

The diagnostic follows the current main.py pipeline as closely as possible:
    store scraper
      -> discovery attempts
      -> identity dedupe
      -> matches()
      -> catalog match / fallback
      -> grouping

It intentionally reports every stage separately so that:
    raw == 0          => discovery/scraper problem
    raw > 0, valid=0  => central validation/matching problem
    valid > 0, grouped lower => grouping/catalog problem

No production code is changed by this script.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List


DEFAULT_QUERY = "Liquid Brun"
DEFAULT_STORE_TIMEOUT = float(os.getenv("SCENTHUNTER_DIAG_STORE_TIMEOUT", "90"))

# Keep this in the diagnostic rather than changing main.py.
STORES = [
    "bplatz",
    "deloox",
    "parfumcity",
    "parfumzentrum",
    "perfumemarket",
    "sabina",
    "orioudh",
    "easycosmetic",
]


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return str(value)


def _compact_product(product: Dict[str, Any]) -> Dict[str, Any]:
    source = product.get("source")
    return {
        "store": product.get("store"),
        "name": product.get("name") or product.get("title") or product.get("product_name"),
        "brand": product.get("brand") or product.get("source_brand"),
        "price": product.get("price"),
        "url": product.get("url"),
        "sku": product.get("sku"),
        "ean": product.get("ean") or product.get("ean13") or product.get("gtin"),
        "product_id": product.get("product_id") or product.get("store_product_id"),
        "variant_id": product.get("variant_id") or product.get("store_variant_id"),
        "family_id": product.get("family_id"),
        "catalog_variant": product.get("catalog_variant"),
        "canonical_name": product.get("canonical_name"),
        "source": source if isinstance(source, dict) else None,
    }


def _identity_key(main: Any, product: Dict[str, Any]) -> str:
    try:
        return repr(main.product_identity_key(product))
    except Exception:
        return repr((
            product.get("store"),
            product.get("name"),
            product.get("url"),
            product.get("sku"),
            product.get("ean"),
        ))


def _discover_store(main: Any, store: str, query: str) -> Dict[str, Any]:
    started = time.monotonic()
    report: Dict[str, Any] = {
        "store": store,
        "query": query,
        "status": "running",
        "elapsed": 0.0,
        "attempts": [],
        "raw_count": 0,
        "raw_unique_count": 0,
        "valid_count": 0,
        "catalog_count": 0,
        "fallback_count": 0,
        "grouped_count": 0,
        "errors": [],
        "raw_results": [],
        "valid_results": [],
        "grouped_results": [],
    }

    try:
        module = importlib.import_module(f"scrapers.{store}.scraper")
        report["module"] = getattr(module, "__file__", None)

        search_fn = getattr(module, "search", None)
        if not callable(search_fn):
            search_fn = getattr(module, "scrape", None)

        if not callable(search_fn):
            raise RuntimeError(
                f"{store}: scraper senza funzione search()/scrape()"
            )

        discovery_query = main.norm(query)
        attempts = main.build_search_attempts(store, discovery_query)
        report["attempts"] = list(attempts)

        seen = set()
        raw_unique: List[Dict[str, Any]] = []

        for attempt in attempts:
            attempt_started = time.monotonic()
            attempt_report = {
                "query": attempt,
                "count": 0,
                "elapsed": 0.0,
                "error": None,
            }

            try:
                results = search_fn(attempt) or []

                if not isinstance(results, list):
                    attempt_report["error"] = (
                        f"invalid_return_type:{type(results).__name__}"
                    )
                    results = []

                for item in results:
                    if not isinstance(item, dict):
                        continue

                    product = dict(item)
                    product.setdefault("store", store)

                    report["raw_count"] += 1
                    attempt_report["count"] += 1

                    key = _identity_key(main, product)
                    if key in seen:
                        continue

                    seen.add(key)
                    raw_unique.append(product)

            except Exception as exc:
                attempt_report["error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                report["errors"].append({
                    "stage": "discovery",
                    "attempt": attempt,
                    "error": attempt_report["error"],
                    "traceback": traceback.format_exc(),
                })

            finally:
                attempt_report["elapsed"] = round(
                    time.monotonic() - attempt_started, 3
                )
                report["attempts"][report["attempts"].index(attempt)] = attempt_report

        report["raw_unique_count"] = len(raw_unique)
        report["raw_results"] = [
            _compact_product(product)
            for product in raw_unique
        ]

        # Reproduce the current run_store post-discovery transformations
        # without changing the production function.
        prepared: List[Dict[str, Any]] = []
        for product in raw_unique:
            try:
                product = main.resolve_actual_price(dict(product))
                image = main.product_image(product)
                if image:
                    product["image"] = image
                prepared.append(product)
            except Exception as exc:
                report["errors"].append({
                    "stage": "post_discovery",
                    "product": _compact_product(product),
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                })

        # Validate one candidate at a time so a single bad candidate cannot
        # hide which other candidates were accepted.
        valid: List[Dict[str, Any]] = []

        for product in prepared:
            try:
                matched = bool(main.matches(product, query))
            except Exception as exc:
                report["errors"].append({
                    "stage": "matches",
                    "product": _compact_product(product),
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                })
                continue

            if not matched:
                continue

            try:
                catalog_product = main._catalog_match(product, query)
            except Exception as exc:
                report["errors"].append({
                    "stage": "catalog_match",
                    "product": _compact_product(product),
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                })
                catalog_product = None

            try:
                if catalog_product is not None:
                    accepted = catalog_product
                    report["catalog_count"] += 1
                else:
                    family = main._catalog_family_for_query(query)
                    if family is not None and main._catalog_product_is_excluded(
                        product, family
                    ):
                        continue

                    accepted = main._apply_generic_display_name(
                        product, query
                    )
                    report["fallback_count"] += 1

                if isinstance(accepted, dict):
                    valid.append(accepted)

            except Exception as exc:
                report["errors"].append({
                    "stage": "validation_finalize",
                    "product": _compact_product(product),
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                })

        report["valid_count"] = len(valid)
        report["valid_results"] = [
            _compact_product(product)
            for product in valid
        ]

        # Reproduce the grouping stage for THIS store only.
        try:
            propagated = main._propagate_catalog_identity(valid)
            grouped = main._group_catalog_results(propagated)
            report["grouped_count"] = len(grouped)
            report["grouped_results"] = [
                _compact_product(product)
                for product in grouped
            ]
        except Exception as exc:
            report["errors"].append({
                "stage": "grouping",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            })

        report["status"] = "ok" if not report["errors"] else "ok_with_errors"

    except Exception as exc:
        report["status"] = "error"
        report["errors"].append({
            "stage": "store",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })

    finally:
        report["elapsed"] = round(time.monotonic() - started, 3)

    return report


def run(query: str) -> Dict[str, Any]:
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(backend_dir)

    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    import main  # noqa: E402

    started = time.monotonic()
    reports: Dict[str, Dict[str, Any]] = {}

    # Store isolation is diagnostic-only: one slow store must not prevent
    # the other seven reports from being collected.
    executor = ThreadPoolExecutor(
        max_workers=len(STORES),
        thread_name_prefix="scenthunter-diag",
    )

    futures = {
        executor.submit(_discover_store, main, store, query): store
        for store in STORES
    }

    try:
        for future in as_completed(
            futures,
            timeout=DEFAULT_STORE_TIMEOUT * len(STORES),
        ):
            store = futures[future]
            try:
                reports[store] = future.result(
                    timeout=DEFAULT_STORE_TIMEOUT
                )
            except Exception as exc:
                reports[store] = {
                    "store": store,
                    "query": query,
                    "status": "error",
                    "elapsed": 0.0,
                    "attempts": [],
                    "raw_count": 0,
                    "raw_unique_count": 0,
                    "valid_count": 0,
                    "catalog_count": 0,
                    "fallback_count": 0,
                    "grouped_count": 0,
                    "errors": [{
                        "stage": "worker",
                        "error": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(),
                    }],
                    "raw_results": [],
                    "valid_results": [],
                    "grouped_results": [],
                }
    except FuturesTimeoutError:
        for future, store in futures.items():
            if store in reports:
                continue
            if future.done():
                try:
                    reports[store] = future.result()
                except Exception as exc:
                    reports[store] = {
                        "store": store,
                        "query": query,
                        "status": "error",
                        "elapsed": 0.0,
                        "errors": [{
                            "stage": "worker",
                            "error": f"{type(exc).__name__}: {exc}",
                            "traceback": traceback.format_exc(),
                        }],
                    }
            else:
                reports[store] = {
                    "store": store,
                    "query": query,
                    "status": "timeout",
                    "elapsed": DEFAULT_STORE_TIMEOUT,
                    "errors": [{
                        "stage": "worker",
                        "error": (
                            f"diagnostic timeout after "
                            f"{DEFAULT_STORE_TIMEOUT}s"
                        ),
                    }],
                }
    finally:
        for future in futures:
            if not future.done():
                future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)

    ordered = [reports[s] for s in STORES if s in reports]

    return {
        "diagnostic": "liquid_brun_pipeline",
        "diagnostic_version": "1.0",
        "query": query,
        "generated_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(),
        ),
        "elapsed": round(time.monotonic() - started, 3),
        "store_timeout": DEFAULT_STORE_TIMEOUT,
        "stores": ordered,
        "summary": {
            "stores_reported": len(ordered),
            "stores_ok": sum(
                1 for r in ordered if r.get("status") == "ok"
            ),
            "stores_with_errors": sum(
                1 for r in ordered
                if r.get("status") == "ok_with_errors"
            ),
            "stores_failed": sum(
                1 for r in ordered
                if r.get("status") in {"error", "timeout"}
            ),
            "raw_candidates": sum(
                int(r.get("raw_unique_count", 0) or 0)
                for r in ordered
            ),
            "valid_candidates": sum(
                int(r.get("valid_count", 0) or 0)
                for r in ordered
            ),
            "grouped_results": sum(
                int(r.get("grouped_count", 0) or 0)
                for r in ordered
            ),
        },
    }


def print_summary(payload: Dict[str, Any]) -> None:
    print()
    print("=" * 100)
    print("SCENTHUNTER — LIQUID BRUN PIPELINE DIAGNOSTIC")
    print("=" * 100)
    print(f"Query: {payload['query']}")
    print()

    header = (
        f"{'STORE':<18}"
        f"{'STATUS':<15}"
        f"{'RAW':>7}"
        f"{'UNIQUE':>8}"
        f"{'VALID':>8}"
        f"{'CAT':>7}"
        f"{'FALL':>7}"
        f"{'GROUP':>8}"
        f"{'SEC':>8}"
    )
    print(header)
    print("-" * len(header))

    for report in payload["stores"]:
        print(
            f"{report.get('store',''):<18}"
            f"{report.get('status',''):<15}"
            f"{report.get('raw_count',0):>7}"
            f"{report.get('raw_unique_count',0):>8}"
            f"{report.get('valid_count',0):>8}"
            f"{report.get('catalog_count',0):>7}"
            f"{report.get('fallback_count',0):>7}"
            f"{report.get('grouped_count',0):>8}"
            f"{report.get('elapsed',0):>8.2f}"
        )

    print()
    print("INTERPRETAZIONE:")
    print("  RAW=0 / UNIQUE=0  -> problema di discovery/scraper.")
    print("  UNIQUE>0 / VALID=0 -> candidati trovati ma respinti dalla validazione.")
    print("  VALID>GROUP        -> perdita nel catalog/grouping.")
    print("  STATUS=timeout     -> problema di timeout/esecuzione, non di matching.")
    print()

    for report in payload["stores"]:
        if not report.get("errors"):
            continue
        print(f"[{report['store']}] ERRORI:")
        for error in report["errors"]:
            print(
                "  -",
                error.get("stage"),
                ":",
                error.get("error"),
            )

    print()
    print("Per il confronto con il runtime, conserva anche il JSON completo.")


def main_cli() -> int:
    query = (
        sys.argv[1].strip()
        if len(sys.argv) > 1 and sys.argv[1].strip()
        else DEFAULT_QUERY
    )

    payload = run(query)
    print_summary(payload)

    output_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "diagnose_liquid_brun_result.json",
    )

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(
            _jsonable(payload),
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(f"JSON salvato in: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
