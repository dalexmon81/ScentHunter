"""
ScentHunter - Point 1 - Generic discovery diagnostic

Questo file NON modifica gli scraper, main.py o l'index.

Serve a isolare il punto esatto in cui un candidato viene perso:

query
 -> build_search_attempts()
 -> scraper.search()/scrape()
 -> risultati grezzi restituiti dallo scraper
 -> deduplicazione per store
 -> matches() centrale
 -> risultati finali

La diagnostica è generica e NON contiene eccezioni per singoli profumi.

Uso:
    python diagnostic_search.py "Liquid Brun Limited Edition"

Il report viene salvato in:
    diagnostic_search_report.json
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import traceback
from typing import Any, Dict, List, Tuple

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)

if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import main as scent_main


STORES = list(scent_main.STORES)


def short(value: Any) -> str:
    return str(value or "").strip()


def safe_product_name(item: Dict[str, Any]) -> str:
    return short(
        scent_main.product_field(
            item,
            "name",
            "title",
            "product_name",
        )
    )


def safe_brand(item: Dict[str, Any]) -> str:
    return short(
        scent_main.product_field(
            item,
            "brand",
            "source_brand",
        )
    )


def candidate_summary(
    item: Dict[str, Any],
    store: str,
    attempt: str,
    raw_index: int,
) -> Dict[str, Any]:
    name = safe_product_name(item)
    brand = safe_brand(item)

    return {
        "store": store,
        "attempt": attempt,
        "raw_index": raw_index,
        "name": name,
        "brand": brand,
        "url": short(item.get("url")),
        "price": short(item.get("price")),
        "available": item.get("available"),
        "availability": short(
            scent_main.product_availability(item)
        ),
        "size_ml": scent_main.product_size_ml(item),
        "concentration": scent_main.product_concentration(item),
        "store_product_id": short(
            scent_main.identity_value(
                item,
                "store_product_id",
                "product_id",
                "catalog_id",
            )
        ),
        "store_variant_id": short(
            scent_main.identity_value(
                item,
                "store_variant_id",
                "variant_id",
            )
        ),
        "gtin": short(
            scent_main.identity_value(
                item,
                "gtin",
                "ean",
                "ean13",
                "barcode",
                "upc",
            )
        ),
        "sku": short(
            scent_main.identity_value(item, "sku")
        ),
    }


def generic_target_overlap(
    item: Dict[str, Any],
    query: str,
) -> Dict[str, Any]:
    """
    Diagnostica puramente informativa.

    NON decide se un candidato è corretto.
    Serve solo a evidenziare risultati grezzi che condividono
    token con la query, così sono facili da controllare.
    """
    query_tokens = [
        token
        for token in scent_main.norm(query).split()
        if token not in scent_main.IGNORED_WORDS
        and token
    ]

    searchable = scent_main.product_search_text(item)
    searchable_tokens = set(searchable.split())

    matched = [
        token
        for token in query_tokens
        if token in searchable_tokens
    ]

    return {
        "query_tokens": query_tokens,
        "matched_tokens": matched,
        "matched_count": len(matched),
        "query_token_count": len(query_tokens),
        "all_query_tokens_present": (
            bool(query_tokens)
            and len(matched) == len(query_tokens)
        ),
    }


def load_search_function(store: str):
    module = importlib.import_module(
        f"scrapers.{store}.scraper"
    )

    search_fn = getattr(module, "search", None)

    if not callable(search_fn):
        search_fn = getattr(module, "scrape", None)

    if not callable(search_fn):
        raise RuntimeError(
            f"{store}: scraper senza funzione search()/scrape()"
        )

    return module, search_fn


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
        "attempts": attempts,
        "status": "ok",
        "raw_total": 0,
        "raw_by_attempt": [],
        "all_raw_candidates": [],
        "deduplicated_candidates": [],
        "duplicates": [],
        "matched_candidates": [],
        "non_matched_candidates": [],
        "errors": [],
    }

    try:
        module, search_fn = load_search_function(store)
        report["scraper_module"] = module.__name__
    except Exception as exc:
        report["status"] = "error"
        report["errors"].append({
            "stage": "load_scraper",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })
        return report

    raw_candidates: List[Tuple[str, int, Dict[str, Any]]] = []

    for attempt in attempts:
        try:
            results = search_fn(attempt) or []
        except Exception as exc:
            report["errors"].append({
                "stage": "scraper_search",
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
                "stage": "scraper_search",
                "attempt": attempt,
                "error": (
                    "Risposta non-list: "
                    f"{type(results).__name__}"
                ),
            })
            report["raw_by_attempt"].append({
                "attempt": attempt,
                "count": 0,
                "status": "invalid_response",
                "response_type": type(results).__name__,
            })
            continue

        report["raw_total"] += len(results)

        attempt_items = []

        for raw_index, item in enumerate(results):
            if not isinstance(item, dict):
                attempt_items.append({
                    "raw_index": raw_index,
                    "invalid_item_type": type(item).__name__,
                })
                continue

            product = dict(item)
            product.setdefault("store", store)

            summary = candidate_summary(
                product,
                store,
                attempt,
                raw_index,
            )
            summary["target_overlap"] = generic_target_overlap(
                product,
                query,
            )

            attempt_items.append(summary)
            raw_candidates.append(
                (attempt, raw_index, product)
            )

        report["raw_by_attempt"].append({
            "attempt": attempt,
            "count": len(results),
            "status": "ok",
            "candidates": attempt_items,
        })

    # Tutti i risultati grezzi vengono conservati, compresi i duplicati.
    report["all_raw_candidates"] = [
        {
            **candidate_summary(
                product,
                store,
                attempt,
                raw_index,
            ),
            "target_overlap": generic_target_overlap(
                product,
                query,
            ),
        }
        for attempt, raw_index, product in raw_candidates
    ]

    # Deduplicazione esattamente con la stessa identity key del main.
    seen = {}

    for attempt, raw_index, product in raw_candidates:
        key = scent_main.product_identity_key(product)

        entry = {
            **candidate_summary(
                product,
                store,
                attempt,
                raw_index,
            ),
            "dedupe_key": list(key),
            "target_overlap": generic_target_overlap(
                product,
                query,
            ),
        }

        if key in seen:
            report["duplicates"].append({
                "duplicate": entry,
                "kept_candidate": seen[key],
            })
            continue

        seen[key] = entry
        report["deduplicated_candidates"].append(entry)

    # La fase successiva viene testata solo dopo la deduplicazione.
    for entry in report["deduplicated_candidates"]:
        product = {
            "store": store,
            "name": entry.get("name"),
            "brand": entry.get("brand"),
            "url": entry.get("url"),
            "price": entry.get("price"),
            "available": entry.get("available"),
            "size_ml": entry.get("size_ml"),
            "concentration": entry.get("concentration"),
            "store_product_id": entry.get("store_product_id"),
            "store_variant_id": entry.get("store_variant_id"),
            "gtin": entry.get("gtin"),
            "sku": entry.get("sku"),
        }

        try:
            matched = bool(
                scent_main.matches(
                    product,
                    query,
                )
            )
        except Exception as exc:
            report["errors"].append({
                "stage": "matches",
                "candidate": entry,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            })
            continue

        if matched:
            report["matched_candidates"].append(entry)
        else:
            report["non_matched_candidates"].append(entry)

    report["summary"] = {
        "attempt_count": len(attempts),
        "raw_total": report["raw_total"],
        "unique_after_dedup": len(
            report["deduplicated_candidates"]
        ),
        "duplicates_removed": len(
            report["duplicates"]
        ),
        "matched_total": len(
            report["matched_candidates"]
        ),
        "non_matched_total": len(
            report["non_matched_candidates"]
        ),
        "error_total": len(report["errors"]),
    }

    return report


def run_query(query: str) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "query": query,
        "stores": {},
        "global_summary": {},
    }

    for store in STORES:
        report["stores"][store] = run_store(
            store,
            query,
        )

    total_raw = 0
    total_unique = 0
    total_duplicates = 0
    total_matched = 0
    total_non_matched = 0
    stores_with_zero_raw = []
    stores_with_matches = []
    stores_with_errors = []

    for store, store_report in report["stores"].items():
        summary = store_report.get("summary", {})

        raw_total = int(
            summary.get("raw_total", 0)
        )
        unique_total = int(
            summary.get("unique_after_dedup", 0)
        )
        duplicate_total = int(
            summary.get("duplicates_removed", 0)
        )
        matched_total = int(
            summary.get("matched_total", 0)
        )
        non_matched_total = int(
            summary.get("non_matched_total", 0)
        )

        total_raw += raw_total
        total_unique += unique_total
        total_duplicates += duplicate_total
        total_matched += matched_total
        total_non_matched += non_matched_total

        if raw_total == 0:
            stores_with_zero_raw.append(store)

        if matched_total > 0:
            stores_with_matches.append(store)

        if store_report.get("errors"):
            stores_with_errors.append(store)

    report["global_summary"] = {
        "stores_total": len(STORES),
        "stores_with_zero_raw": stores_with_zero_raw,
        "stores_with_matches": stores_with_matches,
        "stores_with_errors": stores_with_errors,
        "raw_total": total_raw,
        "unique_after_dedup": total_unique,
        "duplicates_removed": total_duplicates,
        "matched_total": total_matched,
        "non_matched_total": total_non_matched,
    }

    return report


def print_report(report: Dict[str, Any]) -> None:
    print()
    print("=" * 78)
    print("SCENTHUNTER - POINT 1 DISCOVERY DIAGNOSTIC")
    print(f"QUERY: {report['query']}")
    print("=" * 78)
    print()

    global_summary = report["global_summary"]

    print("GLOBAL SUMMARY")
    print(
        f"  Raw restituiti dagli scraper : "
        f"{global_summary['raw_total']}"
    )
    print(
        f"  Unici dopo dedup             : "
        f"{global_summary['unique_after_dedup']}"
    )
    print(
        f"  Duplicati rimossi            : "
        f"{global_summary['duplicates_removed']}"
    )
    print(
        f"  Accettati da matches()       : "
        f"{global_summary['matched_total']}"
    )
    print(
        f"  Rifiutati da matches()       : "
        f"{global_summary['non_matched_total']}"
    )
    print()

    for store, store_report in report["stores"].items():
        summary = store_report.get("summary", {})

        print("-" * 78)
        print(f"STORE: {store}")
        print(
            f"  Attempts       : "
            f"{summary.get('attempt_count', 0)}"
        )
        print(
            f"  Raw            : "
            f"{summary.get('raw_total', 0)}"
        )
        print(
            f"  Unici          : "
            f"{summary.get('unique_after_dedup', 0)}"
        )
        print(
            f"  Duplicati      : "
            f"{summary.get('duplicates_removed', 0)}"
        )
        print(
            f"  matches() TRUE : "
            f"{summary.get('matched_total', 0)}"
        )
        print(
            f"  matches() FALSE: "
            f"{summary.get('non_matched_total', 0)}"
        )
        print(
            f"  Errori         : "
            f"{summary.get('error_total', 0)}"
        )

        print("  DISCOVERY PER QUERY:")
        for attempt_data in store_report.get(
            "raw_by_attempt",
            [],
        ):
            print(
                f"    - {attempt_data.get('attempt')!r}: "
                f"{attempt_data.get('count', 0)} raw"
            )

        if store_report.get("all_raw_candidates"):
            print("  RAW CANDIDATES:")
            for candidate in store_report[
                "all_raw_candidates"
            ]:
                overlap = candidate.get(
                    "target_overlap",
                    {},
                )
                print(
                    f"    [{candidate.get('attempt')!r}] "
                    f"{candidate.get('name') or '-'}"
                    f" | {candidate.get('brand') or '-'}"
                    f" | {candidate.get('url') or '-'}"
                    f" | overlap="
                    f"{overlap.get('matched_tokens', [])}"
                )

        if store_report.get("duplicates"):
            print("  DUPLICATI:")
            for duplicate in store_report[
                "duplicates"
            ]:
                dup = duplicate["duplicate"]
                kept = duplicate["kept_candidate"]
                print(
                    f"    - {dup.get('name') or '-'}"
                    f" -> duplicate di "
                    f"{kept.get('name') or '-'}"
                )

        if store_report.get("non_matched_candidates"):
            print("  RIFIUTATI DA matches():")
            for candidate in store_report[
                "non_matched_candidates"
            ]:
                print(
                    f"    - {candidate.get('name') or '-'}"
                    f" | {candidate.get('url') or '-'}"
                )

        if store_report.get("errors"):
            print("  ERRORI:")
            for error in store_report["errors"]:
                print(
                    f"    - {error.get('stage')}: "
                    f"{error.get('error')}"
                )

    print()
    print("=" * 78)
    print("INTERPRETAZIONE")
    print("=" * 78)
    print(
        "1. Raw = 0: il candidato non è arrivato "
        "all'orchestratore dallo scraper."
    )
    print(
        "2. Raw > 0 ma il prodotto non è tra i candidati: "
        "controllare i risultati grezzi restituiti dallo scraper."
    )
    print(
        "3. Il candidato è raw ma sparisce tra gli unici: "
        "controllare la product_identity_key/deduplicazione."
    )
    print(
        "4. Il candidato è unico ma matches() è FALSE: "
        "solo in questo caso passare alla fase matching."
    )
    print()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument(
        "--output",
        default=os.path.join(
            CURRENT_DIR,
            "diagnostic_search_report.json",
        ),
    )
    args = parser.parse_args()

    query = short(args.query)

    if not query:
        raise SystemExit("Query vuota.")

    report = run_query(query)

    output_path = os.path.abspath(
        args.output
    )

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

    print_report(report)
    print()
    print(f"REPORT JSON: {output_path}")


if __name__ == "__main__":
    main()
