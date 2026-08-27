"""
ScentHunter - global search pipeline diagnostic

Questo modulo è usato dall'endpoint diagnostico HTTP.
Non modifica la pipeline normale di ricerca.

Espone:
    run_query(query, stores=None)

e, per compatibilità, anche una CLI locale.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from typing import Any, Dict, List, Optional


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)

if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import main as scent_main


STORES = list(scent_main.STORES)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _name(item: Dict[str, Any]) -> str:
    return _text(
        scent_main.product_field(
            item,
            "name",
            "title",
            "product_name",
        )
    )


def _store(item: Dict[str, Any]) -> str:
    return _text(item.get("store"))


def _identity(item: Dict[str, Any]) -> Any:
    return scent_main.product_identity_key(item)


def _central_match(
    item: Dict[str, Any],
    query: str,
) -> bool:
    try:
        return bool(scent_main.matches(item, query))
    except Exception:
        return False


def run_store(
    store: str,
    query: str,
) -> Dict[str, Any]:
    attempts = scent_main.build_search_attempts(
        store,
        query,
    )

    report: Dict[str, Any] = {
        "store": store,
        "status": "ok",
        "attempts": attempts,
        "calls": [],
        "returned_total": 0,
        "unique_candidates": 0,
        "central_matches": 0,
        "central_rejected": 0,
        "errors": [],
        "products": [],
    }

    try:
        module = importlib.import_module(
            f"scrapers.{store}.scraper"
        )
    except Exception as exc:
        report["status"] = "import_error"
        report["errors"].append(
            f"{type(exc).__name__}: {exc}"
        )
        return report

    search_fn = getattr(module, "search", None)

    if not callable(search_fn):
        search_fn = getattr(module, "scrape", None)

    if not callable(search_fn):
        report["status"] = "missing_search_function"
        report["errors"].append(
            "Lo scraper non espone search()/scrape()"
        )
        return report

    seen = set()

    for attempt in attempts:
        call = {
            "query": attempt,
            "returned": 0,
            "unique_added": 0,
            "central_matches": 0,
            "central_rejected": 0,
            "error": None,
        }

        try:
            results = search_fn(attempt) or []

            if not isinstance(results, list):
                results = []

            call["returned"] = len(results)
            report["returned_total"] += len(results)

            for item in results:
                if not isinstance(item, dict):
                    continue

                product = dict(item)
                product.setdefault("store", store)

                key = _identity(product)

                if key in seen:
                    continue

                seen.add(key)

                call["unique_added"] += 1
                report["unique_candidates"] += 1

                matches = _central_match(
                    product,
                    query,
                )

                if matches:
                    call["central_matches"] += 1
                    report["central_matches"] += 1
                else:
                    call["central_rejected"] += 1
                    report["central_rejected"] += 1

                report["products"].append(
                    {
                        "name": _name(product),
                        "store": (
                            _store(product)
                            or store
                        ),
                        "url": _text(
                            product.get("url")
                        ),
                        "price": _text(
                            product.get("price")
                        ),
                        "available": product.get(
                            "available"
                        ),
                        "availability": _text(
                            scent_main.product_availability(
                                product
                            )
                        ),
                        "identity_key": list(key),
                        "central_matches": matches,
                        "family_id": _text(
                            product.get("family_id")
                        ),
                        "canonical_name": _text(
                            product.get(
                                "canonical_name"
                            )
                        ),
                        "catalog_variant": _text(
                            product.get(
                                "catalog_variant"
                            )
                        ),
                    }
                )

        except Exception as exc:
            error = (
                f"{attempt}: "
                f"{type(exc).__name__}: {exc}"
            )

            call["error"] = error
            report["errors"].append(error)

        report["calls"].append(call)

    if report["errors"] and not report["products"]:
        report["status"] = "error"
    elif not report["products"]:
        report["status"] = "zero_candidates"
    elif report["central_matches"] == 0:
        report["status"] = (
            "candidates_rejected_by_central_match"
        )
    else:
        report["status"] = (
            "candidate_reaches_central_match"
        )

    return report


def build_report(
    query: str,
    stores: List[str],
) -> Dict[str, Any]:
    reports = [
        run_store(
            store,
            query,
        )
        for store in stores
    ]

    return {
        "query": query,
        "stores_expected": len(stores),
        "stores_with_raw_candidates": sum(
            report["raw_candidates"]
            if "raw_candidates" in report
            else report["returned_total"] > 0
            for report in reports
        ),
        "stores_with_candidates": sum(
            bool(report["products"])
            for report in reports
        ),
        "stores_with_central_matches": sum(
            report["central_matches"] > 0
            for report in reports
        ),
        "stores_with_errors": sum(
            bool(report["errors"])
            for report in reports
        ),
        "stores_with_zero_candidates": sum(
            not report["products"]
            for report in reports
        ),
        "stores": reports,
    }


def run_query(
    query: str,
    stores: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Entry point per l'endpoint HTTP.

    Non usa argparse e restituisce direttamente un dict
    serializzabile da FastAPI.
    """
    query = _text(query)

    if not query:
        raise ValueError(
            "La query non può essere vuota."
        )

    selected_stores = (
        list(stores)
        if stores is not None
        else list(STORES)
    )

    invalid = [
        store
        for store in selected_stores
        if store not in STORES
    ]

    if invalid:
        raise ValueError(
            "Store non validi: "
            + ", ".join(invalid)
            + ". Disponibili: "
            + ", ".join(STORES)
        )

    reports = [
        run_store(
            store,
            query,
        )
        for store in selected_stores
    ]

    final_results = []

    for report in reports:
        if report["central_matches"] <= 0:
            continue

        for product in report["products"]:
            if not product["central_matches"]:
                continue

            final_results.append(
                {
                    "store": (
                        product["store"]
                        or report["store"]
                    ),
                    "name": product["name"],
                    "url": product["url"],
                    "price": product["price"],
                    "identity_key": product[
                        "identity_key"
                    ],
                    "match_method": "raw_identity",
                    "canonical_name": (
                        product["canonical_name"]
                        or product["name"]
                    ),
                }
            )

    raw_candidates = sum(
        report["returned_total"]
        for report in reports
    )

    unique_candidates = sum(
        report["unique_candidates"]
        for report in reports
    )

    central_matches = sum(
        report["central_matches"]
        for report in reports
    )

    central_rejected = sum(
        report["central_rejected"]
        for report in reports
    )

    return {
        "ok": True,
        "query": query,
        "expected_stores": len(selected_stores),
        "stores_with_raw_candidates": sum(
            report["returned_total"] > 0
            for report in reports
        ),
        "stores_with_central_matches": sum(
            report["central_matches"] > 0
            for report in reports
        ),
        "stores_with_final_results": len(
            {
                result["store"]
                for result in final_results
            }
        ),
        "global": {
            "raw_candidates": raw_candidates,
            "unique_candidates": unique_candidates,
            "central_matches": central_matches,
            "central_rejected": central_rejected,
            "final_results": len(final_results),
        },
        "final_by_store": {
            store: sum(
                result["store"].lower()
                == store.lower()
                for result in final_results
            )
            for store in selected_stores
        },
        "errors": {
            report["store"]: report["errors"]
            for report in reports
            if report["errors"]
        },
        "stores": reports,
        "final_results": final_results,
    }


def print_report(
    report: Dict[str, Any],
) -> None:
    print()
    print(
        f"QUERY: {report['query']}"
    )
    print(
        "COPERTURA SCRAPER: "
        f"{report['stores_with_candidates']}/"
        f"{report['stores_expected']}"
    )
    print(
        "COPERTURA MATCHER: "
        f"{report['stores_with_central_matches']}/"
        f"{report['stores_expected']}"
    )
    print()

    for item in report["stores"]:
        print(
            f"{item['store']:16} "
            f"{item['status']:34} "
            f"returned={item['returned_total']:3} "
            f"unique={item['unique_candidates']:3} "
            f"matched={item['central_matches']:3} "
            f"rejected={item['central_rejected']:3}"
        )

        for call in item["calls"]:
            print(
                "  "
                f"query={call['query']!r} "
                f"returned={call['returned']} "
                f"unique+={call['unique_added']} "
                f"matched={call['central_matches']} "
                f"rejected={call['central_rejected']}"
            )

        for product in item["products"]:
            print(
                "    - "
                f"{product['name']} | "
                f"central_match="
                f"{product['central_matches']} | "
                f"{product['url']}"
            )

        for error in item["errors"]:
            print(
                f"    ! {error}"
            )

        print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnostica globale della pipeline "
            "ScentHunter."
        )
    )

    parser.add_argument(
        "query",
        help="Termine di ricerca da testare.",
    )

    parser.add_argument(
        "--stores",
        nargs="*",
        choices=STORES,
        default=STORES,
        help="Limita il test a determinati store.",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Restituisce soltanto JSON.",
    )

    args = parser.parse_args()

    query = _text(args.query)

    if not query:
        parser.error(
            "La query non può essere vuota."
        )

    report = run_query(
        query,
        stores=list(args.stores),
    )

    if args.json:
        print(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print_report(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
