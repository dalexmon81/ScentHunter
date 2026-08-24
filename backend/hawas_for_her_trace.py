"""
ScentHunter - Hawas For Her Trace Diagnostic

Diagnostic-only utility.
It does NOT modify scraper logic, main.py, matcher, registry, or frontend.

Purpose:
    Compare the generic family query "Hawas" with the exact variant query
    "Hawas For Her" at the discovery root, so we can identify the stage at
    which the variant disappears.

It reuses the existing discovery_root_diagnostic.py probes already present
in the project. No production scraper is changed.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from discovery_root_diagnostic import (
    STORES,
    clean,
    inspect_module,
    raw_search_probe,
    reader_probe,
    sitemap_probe,
    run_current_scraper,
)


BASE_QUERY = "Hawas"
TARGET_QUERY = "Hawas For Her"

# Stores where the variant has already been observed to be missing.
# This is a diagnostic scope, not a production rule.
DEFAULT_STORES = (
    "deloox",
    "notino",
    "perfumemarket",
)


def compact_scraper_results(data: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only identity/reachability information useful for the trace."""
    results = data.get("results") or []
    compact = []

    for item in results:
        if not isinstance(item, dict):
            continue

        source = item.get("source") or {}
        identity = item.get("identity") or {}
        attributes = item.get("attributes") or {}

        compact.append(
            {
                "name": source.get("source_name") or item.get("name"),
                "brand": source.get("source_brand") or item.get("brand"),
                "url": source.get("url") or item.get("url"),
                "store_product_id": identity.get("store_product_id"),
                "size_ml": (
                    (attributes.get("size_ml") or {}).get("value")
                    if isinstance(attributes.get("size_ml"), dict)
                    else attributes.get("size_ml")
                ),
            }
        )

    return {
        "attempted": data.get("attempted"),
        "count": data.get("count"),
        "error": data.get("error"),
        "results": compact,
    }


def run_probe(store: str, query: str) -> Dict[str, Any]:
    raw = raw_search_probe(store, query)
    reader = reader_probe(store, query)
    sitemap = sitemap_probe(store, query)
    scraper = run_current_scraper(store, query)

    return {
        "query": query,
        "module": inspect_module(store),
        "raw_search": raw,
        "reader": reader,
        "sitemap": sitemap,
        "current_scraper": compact_scraper_results(scraper),
    }


def classify_transition(base: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    base_scraper = base["current_scraper"]
    target_scraper = target["current_scraper"]

    base_count = base_scraper.get("count")
    target_count = target_scraper.get("count")

    base_raw = base["raw_search"]
    target_raw = target["raw_search"]

    target_has_raw_links = target_raw.get("any_product_links", False)
    target_has_matching_links = target_raw.get("any_matching_links", False)

    if target_count not in (None, 0):
        stage = "SCRAPER_REACHES_TARGET"
        explanation = (
            "La query esatta raggiunge il current scraper. "
            "Il problema della query generica è nella discovery della famiglia "
            "o nella profondità/paginazione della ricerca."
        )
    elif target_has_matching_links:
        stage = "POST_DISCOVERY_VALIDATION"
        explanation = (
            "La pagina di ricerca espone già link compatibili con la query esatta, "
            "ma il current scraper restituisce 0: il candidato viene perso dopo "
            "la discovery."
        )
    elif target_has_raw_links:
        stage = "SEARCH_SELECTOR_OR_MATCHING"
        explanation = (
            "La risposta HTML contiene prodotti, ma il probe non trova un link "
            "che soddisfi tutti i token della query esatta."
        )
    else:
        stage = "SEARCH_DISCOVERY"
        explanation = (
            "Il canale HTTP analizzato non espone link prodotto compatibili "
            "con la query esatta. Il candidato viene perso alla discovery."
        )

    return {
        "base_query_count": base_count,
        "target_query_count": target_count,
        "stage": stage,
        "explanation": explanation,
        "generic_query_finds_some_results": bool(base_count),
        "exact_query_finds_target": bool(target_count),
    }


def trace_store(store: str) -> Dict[str, Any]:
    base = run_probe(store, BASE_QUERY)
    target = run_probe(store, TARGET_QUERY)

    return {
        "store": store,
        "transition": classify_transition(base, target),
        "base_query": base,
        "target_query": target,
    }


def run_trace(stores=None) -> Dict[str, Any]:
    stores = tuple(stores or DEFAULT_STORES)

    unknown = [store for store in stores if store not in STORES]
    if unknown:
        raise ValueError(
            f"Store non supportati dal diagnostic root: {unknown}. "
            f"Disponibili: {list(STORES)}"
        )

    return {
        "diagnostic": "hawas_for_her_trace",
        "production_files_modified": False,
        "base_query": BASE_QUERY,
        "target_query": TARGET_QUERY,
        "stores": {
            store: trace_store(store)
            for store in stores
        },
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Trace diagnostico Hawas -> Hawas For Her"
    )
    parser.add_argument(
        "--stores",
        nargs="*",
        default=list(DEFAULT_STORES),
        help="Store da diagnosticare",
    )

    args = parser.parse_args()

    print(
        json.dumps(
            run_trace(args.stores),
            ensure_ascii=False,
            indent=2,
        )
    )
