"""
ScentHunter - Point 1 diagnostic runner

Questo file NON modifica la logica degli scraper e NON sostituisce main.py.
Serve esclusivamente a fotografare il comportamento della versione stabile.

Uso:
    python diagnostic_search.py "Liquid Brun"
    python diagnostic_search.py "Liquid Brun Limited Edition"

Il report viene stampato a video e salvato in:
    diagnostic_report.json

Il runner usa le funzioni già presenti in backend.main:
- build_search_attempts
- matches
- resolve_actual_price
- product_identity_key

Gli scraper vengono chiamati direttamente, senza modificare il loro codice.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import datetime, timezone
from typing import Any, Dict, List

# Permette di eseguire il file sia da backend/ sia dalla root del progetto.
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)

if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import main as scent_main


STORES = list(scent_main.STORES)
GLOBAL_TIMEOUT = int(getattr(scent_main, "GLOBAL_SEARCH_TIMEOUT", 120))


def safe_name(product: Dict[str, Any]) -> str:
    value = scent_main.product_field(
        product,
        "name",
        "title",
        "product_name",
    )
    return str(value or "").strip()


def safe_url(product: Dict[str, Any]) -> str:
    return str(product.get("url") or "").strip()


def candidate_key(product: Dict[str, Any]) -> str:
    try:
        return repr(scent_main.product_identity_key(product))
    except Exception:
        return f"url:{safe_url(product)}|name:{safe_name(product)}"


def summarize_product(product: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": safe_name(product),
        "url": safe_url(product),
        "store": str(product.get("store") or ""),
        "price": str(product.get("price") or ""),
        "available": product.get("available"),
        "availability": scent_main.product_availability(product),
        "size_ml": scent_main.product_size_ml(product),
        "concentration": scent_main.product_concentration(product),
        "identity_key": candidate_key(product),
    }


def run_store_diagnostic(store: str, query: str) -> Dict[str, Any]:
    started = time.perf_counter()

    report: Dict[str, Any] = {
        "store": store,
        "status": "ok",
        "elapsed_seconds": 0.0,
        "attempts": [],
        "totals": {
            "raw_items": 0,
            "dict_items": 0,
            "unique_candidates": 0,
            "valid_candidates": 0,
            "duplicates": 0,
        },
        "final_results": [],
    }

    try:
        module = importlib.import_module(f"scrapers.{store}.scraper")

        search_fn = getattr(module, "search", None)
        if not callable(search_fn):
            search_fn = getattr(module, "scrape", None)

        if not callable(search_fn):
            raise RuntimeError(
                f"{store}: scraper senza funzione search()/scrape()"
            )

        attempts = scent_main.build_search_attempts(store, query)

        global_seen = set()
        final_results: List[Dict[str, Any]] = []

        for attempt_index, attempt in enumerate(attempts, start=1):
            attempt_started = time.perf_counter()

            attempt_report: Dict[str, Any] = {
                "index": attempt_index,
                "query": attempt,
                "status": "ok",
                "elapsed_seconds": 0.0,
                "raw_items": 0,
                "dict_items": 0,
                "unique_candidates": 0,
                "duplicates": 0,
                "valid_candidates": 0,
                "invalid_candidates": 0,
                "raw_candidates": [],
                "valid_candidates_detail": [],
                "invalid_candidates_detail": [],
            }

            try:
                results = search_fn(attempt) or []
                if not isinstance(results, list):
                    results = []

                attempt_report["raw_items"] = len(results)
                report["totals"]["raw_items"] += len(results)

                for item in results:
                    if not isinstance(item, dict):
                        continue

                    attempt_report["dict_items"] += 1
                    report["totals"]["dict_items"] += 1

                    product = dict(item)
                    product.setdefault("store", store)

                    try:
                        product = scent_main.resolve_actual_price(product)
                    except Exception:
                        pass

                    key = candidate_key(product)

                    if key in global_seen:
                        attempt_report["duplicates"] += 1
                        report["totals"]["duplicates"] += 1
                        continue

                    global_seen.add(key)

                    attempt_report["unique_candidates"] += 1
                    report["totals"]["unique_candidates"] += 1

                    candidate_summary = summarize_product(product)
                    attempt_report["raw_candidates"].append(candidate_summary)

                    try:
                        valid = bool(scent_main.matches(product, query))
                    except Exception as exc:
                        valid = False
                        candidate_summary["validation_error"] = (
                            f"{type(exc).__name__}: {exc}"
                        )

                    if valid:
                        attempt_report["valid_candidates"] += 1
                        report["totals"]["valid_candidates"] += 1
                        attempt_report["valid_candidates_detail"].append(
                            candidate_summary
                        )
                        final_results.append(product)
                    else:
                        attempt_report["invalid_candidates"] += 1
                        attempt_report["invalid_candidates_detail"].append(
                            candidate_summary
                        )

            except Exception as exc:
                attempt_report["status"] = "error"
                attempt_report["error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                attempt_report["traceback"] = traceback.format_exc()

            attempt_report["elapsed_seconds"] = round(
                time.perf_counter() - attempt_started,
                3,
            )
            report["attempts"].append(attempt_report)

        # IMPORTANT:
        # Unlike main.py, this diagnostic runner does NOT stop after the first
        # successful attempt. It records every configured attempt so we can
        # see whether a later attempt would have discovered additional valid
        # candidates.
        report["final_results"] = [
            summarize_product(product)
            for product in final_results
        ]

    except Exception as exc:
        report["status"] = "error"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()

    report["elapsed_seconds"] = round(
        time.perf_counter() - started,
        3,
    )

    return report


def print_report(report: Dict[str, Any]) -> None:
    print()
    print("=" * 78)
    print(f"STORE: {report['store']}")
    print(
        f"STATUS: {report['status']} | "
        f"TEMPO: {report['elapsed_seconds']:.3f}s"
    )

    if report.get("error"):
        print(f"ERROR: {report['error']}")
        return

    totals = report["totals"]
    print(
        "TOTALI: "
        f"raw={totals['raw_items']} | "
        f"dict={totals['dict_items']} | "
        f"unique={totals['unique_candidates']} | "
        f"validi={totals['valid_candidates']} | "
        f"duplicati={totals['duplicates']}"
    )

    for attempt in report["attempts"]:
        print()
        print(
            f"  TENTATIVO {attempt['index']}: "
            f"{attempt['query']!r}"
        )
        print(
            f"    tempo={attempt['elapsed_seconds']:.3f}s | "
            f"raw={attempt['raw_items']} | "
            f"unique={attempt['unique_candidates']} | "
            f"validi={attempt['valid_candidates']} | "
            f"invalidi={attempt['invalid_candidates']} | "
            f"duplicati={attempt['duplicates']}"
        )

        if attempt.get("error"):
            print(f"    ERRORE: {attempt['error']}")

        if attempt["valid_candidates_detail"]:
            print("    CANDIDATI VALIDI:")
            for item in attempt["valid_candidates_detail"]:
                print(
                    f"      - {item['name'] or '(senza nome)'}"
                    f" | {item['price'] or '-'}"
                    f" | {item['url'] or '-'}"
                )

        if attempt["invalid_candidates_detail"]:
            print("    CANDIDATI SCARTATI:")
            for item in attempt["invalid_candidates_detail"]:
                reason = item.get("validation_error", "matches=False")
                print(
                    f"      - {item['name'] or '(senza nome)'}"
                    f" | motivo={reason}"
                )

    print()
    print("RISULTATI COMPLESSIVI DELLA DIAGNOSTICA:")
    for item in report["final_results"]:
        print(
            f"  - {item['name'] or '(senza nome)'}"
            f" | {item['price'] or '-'}"
            f" | {item['url'] or '-'}"
        )


def run(query: str, timeout: int = GLOBAL_TIMEOUT) -> Dict[str, Any]:
    started = time.perf_counter()

    report: Dict[str, Any] = {
        "tool": "ScentHunter Point 1 Diagnostic",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "global_timeout_seconds": timeout,
        "stores": {},
        "summary": {
            "stores_completed": 0,
            "stores_timeout": 0,
            "stores_error": 0,
            "total_valid_candidates": 0,
            "total_unique_candidates": 0,
        },
    }

    executor = ThreadPoolExecutor(
        max_workers=len(STORES),
        thread_name_prefix="scent_diag",
    )

    futures = {
        executor.submit(
            run_store_diagnostic,
            store,
            query,
        ): store
        for store in STORES
    }

    try:
        try:
            for future in as_completed(
                futures,
                timeout=timeout,
            ):
                store = futures[future]

                try:
                    store_report = future.result()
                except Exception as exc:
                    store_report = {
                        "store": store,
                        "status": "error",
                        "elapsed_seconds": 0.0,
                        "error": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(),
                        "attempts": [],
                        "totals": {
                            "raw_items": 0,
                            "dict_items": 0,
                            "unique_candidates": 0,
                            "valid_candidates": 0,
                            "duplicates": 0,
                        },
                        "final_results": [],
                    }

                report["stores"][store] = store_report
                report["summary"]["stores_completed"] += 1

        except TimeoutError:
            for future, store in futures.items():
                if store in report["stores"]:
                    continue

                if future.done():
                    try:
                        store_report = future.result()
                    except Exception as exc:
                        store_report = {
                            "store": store,
                            "status": "error",
                            "elapsed_seconds": 0.0,
                            "error": f"{type(exc).__name__}: {exc}",
                            "traceback": traceback.format_exc(),
                            "attempts": [],
                            "totals": {
                                "raw_items": 0,
                                "dict_items": 0,
                                "unique_candidates": 0,
                                "valid_candidates": 0,
                                "duplicates": 0,
                            },
                            "final_results": [],
                        }
                else:
                    store_report = {
                        "store": store,
                        "status": "timeout",
                        "elapsed_seconds": round(
                            time.perf_counter() - started,
                            3,
                        ),
                        "error": (
                            "Timeout: store ancora in esecuzione "
                            "alla scadenza globale"
                        ),
                        "attempts": [],
                        "totals": {
                            "raw_items": 0,
                            "dict_items": 0,
                            "unique_candidates": 0,
                            "valid_candidates": 0,
                            "duplicates": 0,
                        },
                        "final_results": [],
                    }

                report["stores"][store] = store_report

    finally:
        for future in futures:
            future.cancel()

        # Non attendiamo thread ancora in esecuzione oltre il timeout.
        executor.shutdown(wait=False, cancel_futures=True)

    for store_report in report["stores"].values():
        status = store_report.get("status")
        if status == "timeout":
            report["summary"]["stores_timeout"] += 1
        elif status == "error":
            report["summary"]["stores_error"] += 1

        totals = store_report.get("totals", {})
        report["summary"]["total_valid_candidates"] += int(
            totals.get("valid_candidates", 0) or 0
        )
        report["summary"]["total_unique_candidates"] += int(
            totals.get("unique_candidates", 0) or 0
        )

    report["elapsed_seconds"] = round(
        time.perf_counter() - started,
        3,
    )

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnostica ScentHunter senza modificare main.py."
    )
    parser.add_argument(
        "query",
        help="Query da analizzare.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=GLOBAL_TIMEOUT,
        help="Timeout globale in secondi.",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(CURRENT_DIR, "diagnostic_report.json"),
        help="Percorso del report JSON.",
    )

    args = parser.parse_args()

    query = str(args.query or "").strip()
    if not query:
        raise SystemExit("Query vuota.")

    report = run(
        query=query,
        timeout=max(1, int(args.timeout)),
    )

    output_path = os.path.abspath(args.output)
    with open(
        output_path,
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            report,
            handle,
            ensure_ascii=False,
            indent=2,
        )

    print()
    print("=" * 78)
    print(f"SCENTHUNTER POINT 1 - DIAGNOSTICA")
    print(f"QUERY: {query}")
    print(
        f"TEMPO TOTALE: "
        f"{report.get('elapsed_seconds', 0):.3f}s"
    )
    print(
        f"STORE COMPLETATI: "
        f"{report['summary']['stores_completed']}"
    )
    print(
        f"STORE TIMEOUT: "
        f"{report['summary']['stores_timeout']}"
    )
    print(
        f"STORE ERRORI: "
        f"{report['summary']['stores_error']}"
    )
    print(
        f"CANDIDATI UNICI TOTALI: "
        f"{report['summary']['total_unique_candidates']}"
    )
    print(
        f"CANDIDATI VALIDI TOTALI: "
        f"{report['summary']['total_valid_candidates']}"
    )
    print(f"REPORT: {output_path}")

    for store in STORES:
        store_report = report["stores"].get(store)
        if store_report:
            print_report(store_report)


if __name__ == "__main__":
    main()
