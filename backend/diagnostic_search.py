"""
ScentHunter - 5 phase pipeline diagnostic

This file is diagnostic only. It does NOT modify main.py, scrapers,
product_index.py, product_matcher.py or the SQLite index.

It follows the five diagnostic phases discussed for the matcher/indexer
contract:

1. contract audit;
2. discovery/extraction separated from validation;
3. canonical_name / catalog_variant preservation;
4. variant-aware identity/grouping audit;
5. rejection diagnostics for every candidate.

Usage from backend/:

    python diagnostic_search.py "YOUR QUERY"

Optional:

    python diagnostic_search.py "YOUR QUERY" --stores bplatz deloox
    python diagnostic_search.py "YOUR QUERY" --json-only
    python diagnostic_search.py "YOUR QUERY" --output diagnostic_search_report.json

The diagnostic uses the real scraper modules and the current main.py.
It is deliberately generic: no product/store-specific rules are embedded.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import re
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List, Optional, Tuple


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)

if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import main as scent_main


DEFAULT_OUTPUT = os.path.join(
    CURRENT_DIR,
    "diagnostic_search_report.json",
)

# Solo per il diagnostico: non modifica il timeout della ricerca normale.
DIAGNOSTIC_STORE_TIMEOUT = float(
    os.getenv("SCENTHUNTER_DIAGNOSTIC_STORE_TIMEOUT", "45")
)
DIAGNOSTIC_GLOBAL_TIMEOUT = float(
    os.getenv("SCENTHUNTER_DIAGNOSTIC_GLOBAL_TIMEOUT", "55")
)


def text(value: Any) -> str:
    return str(value or "").strip()


def normalized(value: Any) -> str:
    return scent_main.norm(value)


def safe_name(item: Dict[str, Any]) -> str:
    return text(
        scent_main.product_field(
            item,
            "name",
            "title",
            "product_name",
        )
    )


def safe_brand(item: Dict[str, Any]) -> str:
    return text(
        scent_main.product_field(
            item,
            "brand",
            "source_brand",
        )
    )


def identity_value(item: Dict[str, Any], *keys: str) -> str:
    return text(
        scent_main.identity_value(
            item,
            *keys,
        )
    )


def base_candidate_summary(
    item: Dict[str, Any],
    store: str,
    attempt: str,
    raw_index: int,
) -> Dict[str, Any]:
    return {
        "store": store,
        "attempt": attempt,
        "raw_index": raw_index,
        "name": safe_name(item),
        "brand": safe_brand(item),
        "url": text(item.get("url")),
        "price": text(item.get("price")),
        "available": item.get("available"),
        "availability": text(
            scent_main.product_availability(item)
        ),
        "size_ml": scent_main.product_size_ml(item),
        "concentration": text(
            scent_main.product_concentration(item)
        ),
        "store_product_id": identity_value(
            item,
            "store_product_id",
            "product_id",
            "catalog_id",
        ),
        "store_variant_id": identity_value(
            item,
            "store_variant_id",
            "variant_id",
        ),
        "gtin": identity_value(
            item,
            "gtin",
            "ean",
            "ean13",
            "barcode",
            "upc",
        ),
        "mpn": identity_value(
            item,
            "mpn",
            "manufacturer_part_number",
            "manufacturerNumber",
        ),
        "sku": identity_value(
            item,
            "sku",
        ),
        "family_id": text(item.get("family_id")),
        "family_name": text(item.get("family_name")),
        "canonical_name": text(item.get("canonical_name")),
        "catalog_variant": text(item.get("catalog_variant")),
        "match_method": text(item.get("match_method")),
    }


def target_overlap(
    item: Dict[str, Any],
    query: str,
) -> Dict[str, Any]:
    query_tokens = [
        token
        for token in normalized(query).split()
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


def current_identity_key(item: Dict[str, Any]) -> List[Any]:
    return list(
        scent_main.product_identity_key(item)
    )


def proposed_variant_key(item: Dict[str, Any]) -> List[str]:
    family_id = text(item.get("family_id"))
    canonical = text(
        item.get("canonical_name")
        or item.get("catalog_variant")
    )

    if family_id and canonical:
        variant = normalized(canonical)
        return [
            family_id,
            variant,
        ]

    return [
        normalized(
            item.get("brand")
            or item.get("source_brand")
        ),
        normalized(
            item.get("name")
            or item.get("title")
            or item.get("product_name")
        ),
    ]


def classify_rejection(
    item: Dict[str, Any],
    query: str,
) -> Dict[str, Any]:
    """
    Diagnostic classification only.

    It never decides acceptance. The authoritative decision remains
    scent_main.matches().
    """
    name = safe_name(item)
    query_normalized = normalized(query)
    name_normalized = normalized(name)

    reasons: List[str] = []

    if not name_normalized:
        reasons.append("missing_product_name")

    if scent_main.has_small_size(item) and not re.search(
        r"(?<!\d)\d+(?:[.,]\d+)?\s*(?:ml|cl)\b",
        query_normalized,
    ):
        reasons.append("small_size_without_requested_size")

    for phrase in scent_main.NON_PERFUME:
        phrase_normalized = normalized(phrase)
        if (
            phrase_normalized
            and phrase_normalized in name_normalized
            and phrase_normalized not in query_normalized
        ):
            reasons.append("non_perfume_product")

    catalog_family = None
    catalog_match = None

    try:
        catalog_family = scent_main._catalog_family_for_query(
            query
        )
    except Exception:
        pass

    if catalog_family is not None:
        try:
            catalog_match = scent_main.catalog_match(
                item,
                query,
            )
        except Exception as exc:
            reasons.append(
                "catalog_validation_error"
            )
            return {
                "reasons": reasons,
                "catalog_family": text(
                    catalog_family.get("family_id")
                ),
                "catalog_match_error": (
                    f"{type(exc).__name__}: {exc}"
                ),
            }

        if catalog_match is None:
            reasons.append(
                "catalog_variant_not_resolved"
            )
    else:
        try:
            generic_match = scent_main.matches(
                item,
                query,
            )
        except Exception:
            generic_match = None

        if generic_match is False:
            reasons.append(
                "generic_match_rejected"
            )

    if not reasons:
        reasons.append(
            "rejected_without_specific_diagnostic_reason"
        )

    return {
        "reasons": list(dict.fromkeys(reasons)),
        "catalog_family": (
            text(catalog_family.get("family_id"))
            if isinstance(catalog_family, dict)
            else ""
        ),
        "catalog_match": (
            {
                "family_id": text(
                    catalog_match.get("family_id")
                ),
                "family_name": text(
                    catalog_match.get("family_name")
                ),
                "canonical_name": text(
                    catalog_match.get("canonical_name")
                ),
                "catalog_variant": text(
                    catalog_match.get("catalog_variant")
                ),
            }
            if isinstance(catalog_match, dict)
            else None
        ),
    }


def audit_contract() -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "phase": 1,
        "status": "unknown",
        "checks": [],
    }

    try:
        source = inspect.getsource(scent_main)
        uses_product_matcher = (
            "ProductMatcher" in source
            or "product_matcher" in source
        )
    except Exception:
        uses_product_matcher = None

    result["checks"].append(
        {
            "check": "central_product_matcher_used_by_main",
            "value": uses_product_matcher,
            "expected": True,
        }
    )

    registry_fields = {
        "family_id": False,
        "family_name": False,
        "canonical_name": False,
        "catalog_variant": False,
        "match_method": False,
    }

    try:
        families = getattr(
            scent_main,
            "FAMILY_REGISTRY",
            [],
        )
        for family in families:
            for variant in family.get("variants", []):
                if variant.get("canonical_name"):
                    registry_fields["canonical_name"] = True
                    registry_fields["catalog_variant"] = True
                    break
            if family.get("family_id"):
                registry_fields["family_id"] = True
            if family.get("query_aliases"):
                registry_fields["family_name"] = True
    except Exception:
        pass

    result["checks"].append(
        {
            "check": "registry_identity_fields",
            "value": registry_fields,
            "expected": {
                "family_id": True,
                "family_name": True,
                "canonical_name": True,
                "catalog_variant": True,
                "match_method": True,
            },
        }
    )

    try:
        import product_matcher

        result["checks"].append(
            {
                "check": "product_matcher_importable",
                "value": True,
            }
        )

        catalog_path = os.path.join(
            CURRENT_DIR,
            "product_catalog.json",
        )

        if os.path.exists(catalog_path):
            with open(
                catalog_path,
                "r",
                encoding="utf-8",
            ) as file:
                payload = json.load(file)

            products = payload.get("products", [])
            if products:
                sample = products[0]
                parsed = (
                    product_matcher.CatalogProduct.from_dict(
                        sample
                    )
                )

                result["checks"].append(
                    {
                        "check": "product_matcher_catalog_schema_compatibility",
                        "value": {
                            "catalog_product_id": text(
                                sample.get("product_id")
                            ),
                            "matcher_catalog_id": parsed.catalog_id,
                            "catalog_canonical_name": text(
                                sample.get("canonical_name")
                            ),
                            "matcher_name": parsed.name,
                            "catalog_brand": text(
                                sample.get("brand_name")
                            ),
                            "matcher_brand": parsed.brand,
                        },
                        "expected": "catalog and matcher fields populated",
                    }
                )
    except Exception as exc:
        result["checks"].append(
            {
                "check": "product_matcher_audit_error",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )

    failed = []
    for check in result["checks"]:
        expected = check.get("expected")
        value = check.get("value")

        if (
            expected is True
            and value is not True
        ):
            failed.append(check["check"])

    result["status"] = (
        "FAIL"
        if failed
        else "PASS"
    )
    result["failed_checks"] = failed
    return result


def run_store(
    store: str,
    query: str,
) -> Dict[str, Any]:
    attempts = scent_main.build_search_attempts(
        store,
        query,
    )

    started = time.perf_counter()
    report: Dict[str, Any] = {
        "store": store,
        "attempts": attempts,
        "status": "ok",
        "timing": {
            "started_at": time.time(),
            "duration_ms": None,
            "import_ms": None,
            "attempts_ms": {},
        },
        "raw_total": 0,
        "raw_by_attempt": [],
        "all_raw_candidates": [],
        "deduplicated_candidates": [],
        "duplicates": [],
        "matched_candidates": [],
        "non_matched_candidates": [],
        "errors": [],
    }

    import_started = time.perf_counter()
    try:
        module = importlib.import_module(
            f"scrapers.{store}.scraper"
        )
        report["timing"]["import_ms"] = round(
            (time.perf_counter() - import_started) * 1000,
            1,
        )
        search_fn = getattr(module, "search", None)
        if not callable(search_fn):
            search_fn = getattr(module, "scrape", None)

        if not callable(search_fn):
            raise RuntimeError(
                f"{store}: scraper senza funzione search()/scrape()"
            )

        report["scraper_module"] = module.__name__

    except Exception as exc:
        report["status"] = "error"
        report["errors"].append(
            {
                "stage": "load_scraper",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
        )
        report["summary"] = {
            "attempt_count": len(attempts),
            "raw_total": 0,
            "unique_after_dedup": 0,
            "duplicates_removed": 0,
            "matched_total": 0,
            "non_matched_total": 0,
            "error_total": len(report["errors"]),
        }
        report["timing"]["duration_ms"] = round(
            (time.perf_counter() - started) * 1000,
            1,
        )
        return report

    raw_candidates: List[
        Tuple[str, int, Dict[str, Any]]
    ] = []

    for attempt in attempts:
        attempt_started = time.perf_counter()
        try:
            results = search_fn(attempt) or []
        except Exception as exc:
            report["errors"].append(
                {
                    "stage": "scraper_search",
                    "attempt": attempt,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }
            )
            elapsed_ms = round(
                (time.perf_counter() - attempt_started) * 1000,
                1,
            )
            report["timing"]["attempts_ms"][attempt] = elapsed_ms
            report["raw_by_attempt"].append(
                {
                    "attempt": attempt,
                    "count": 0,
                    "status": "error",
                    "duration_ms": elapsed_ms,
                }
            )
            continue

        if not isinstance(results, list):
            report["errors"].append(
                {
                    "stage": "scraper_search",
                    "attempt": attempt,
                    "error": (
                        "Risposta non-list: "
                        f"{type(results).__name__}"
                    ),
                }
            )
            elapsed_ms = round(
                (time.perf_counter() - attempt_started) * 1000,
                1,
            )
            report["timing"]["attempts_ms"][attempt] = elapsed_ms
            report["raw_by_attempt"].append(
                {
                    "attempt": attempt,
                    "count": 0,
                    "status": "invalid_response",
                    "response_type": type(results).__name__,
                    "duration_ms": elapsed_ms,
                }
            )
            continue

        report["raw_total"] += len(results)

        attempt_items = []

        for raw_index, item in enumerate(results):
            if not isinstance(item, dict):
                attempt_items.append(
                    {
                        "raw_index": raw_index,
                        "invalid_item_type": type(item).__name__,
                    }
                )
                continue

            product = dict(item)
            product.setdefault("store", store)

            summary = base_candidate_summary(
                product,
                store,
                attempt,
                raw_index,
            )
            summary["target_overlap"] = target_overlap(
                product,
                query,
            )
            summary["current_identity_key"] = (
                current_identity_key(product)
            )
            summary["proposed_variant_key"] = (
                proposed_variant_key(product)
            )

            attempt_items.append(summary)
            raw_candidates.append(
                (
                    attempt,
                    raw_index,
                    product,
                )
            )

        elapsed_ms = round(
            (time.perf_counter() - attempt_started) * 1000,
            1,
        )
        report["timing"]["attempts_ms"][attempt] = elapsed_ms
        report["raw_by_attempt"].append(
            {
                "attempt": attempt,
                "count": len(results),
                "status": "ok",
                "duration_ms": elapsed_ms,
                "candidates": attempt_items,
            }
        )

    report["all_raw_candidates"] = [
        {
            **base_candidate_summary(
                product,
                store,
                attempt,
                raw_index,
            ),
            "target_overlap": target_overlap(
                product,
                query,
            ),
            "current_identity_key": current_identity_key(
                product
            ),
            "proposed_variant_key": proposed_variant_key(
                product
            ),
        }
        for attempt, raw_index, product
        in raw_candidates
    ]

    seen = {}

    for attempt, raw_index, product in raw_candidates:
        key = current_identity_key(product)

        entry = {
            **base_candidate_summary(
                product,
                store,
                attempt,
                raw_index,
            ),
            "dedupe_key": list(key),
            "target_overlap": target_overlap(
                product,
                query,
            ),
            "proposed_variant_key": proposed_variant_key(
                product
            ),
        }

        if tuple(key) in seen:
            report["duplicates"].append(
                {
                    "duplicate": entry,
                    "kept_candidate": seen[
                        tuple(key)
                    ],
                }
            )
            continue

        seen[tuple(key)] = entry
        report["deduplicated_candidates"].append(entry)

    for entry in report["deduplicated_candidates"]:
        # Usa il candidato originale completo. Il matcher centrale può
        # dipendere da source, identity, attributes e offer; ricostruirlo
        # dai soli campi riassunti rendeva il diagnostico diverso dalla
        # pipeline reale.
        original = None
        for raw_attempt, raw_index, raw_product in raw_candidates:
            if (
                raw_attempt == entry.get("attempt")
                and raw_index == entry.get("raw_index")
            ):
                original = raw_product
                break

        if isinstance(original, dict):
            product = dict(original)
            product.setdefault("store", store)
        else:
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
                "mpn": entry.get("mpn"),
                "sku": entry.get("sku"),
            }

        match_started = time.perf_counter()
        try:
            matched = bool(
                scent_main.matches(
                    product,
                    query,
                )
            )
            entry["match_duration_ms"] = round(
                (time.perf_counter() - match_started) * 1000,
                1,
            )
        except Exception as exc:
            entry["match_duration_ms"] = round(
                (time.perf_counter() - match_started) * 1000,
                1,
            )
            report["errors"].append(
                {
                    "stage": "matches",
                    "candidate": entry,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }
            )
            continue

        if matched:
            catalog_result = None
            try:
                catalog_result = scent_main.catalog_match(
                    product,
                    query,
                )
            except Exception:
                catalog_result = None

            if isinstance(catalog_result, dict):
                enriched = dict(product)
                enriched.update(
                    {
                        "family_id": text(
                            catalog_result.get("family_id")
                        ),
                        "family_name": text(
                            catalog_result.get("family_name")
                        ),
                        "canonical_name": text(
                            catalog_result.get("canonical_name")
                        ),
                        "catalog_variant": text(
                            catalog_result.get("catalog_variant")
                        ),
                    }
                )
                entry["resolved_identity"] = {
                    "family_id": enriched["family_id"],
                    "family_name": enriched["family_name"],
                    "canonical_name": enriched["canonical_name"],
                    "catalog_variant": enriched["catalog_variant"],
                    "current_identity_key": current_identity_key(
                        enriched
                    ),
                    "proposed_variant_key": proposed_variant_key(
                        enriched
                    ),
                }

            report["matched_candidates"].append(entry)

        else:
            diagnostic = classify_rejection(
                product,
                query,
            )
            entry["rejection_diagnostic"] = diagnostic
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
        "error_total": len(
            report["errors"]
        ),
    }

    report["timing"]["duration_ms"] = round(
        (time.perf_counter() - started) * 1000,
        1,
    )
    return report


def run_query(
    query: str,
    stores: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Esegue TUTTI gli scraper in parallelo e misura ogni fase.

    Questo è volutamente separato dalla pipeline normale: serve a capire
    se un negozio non produce candidati, se è lento, se genera errori,
    oppure se i candidati vengono eliminati dal matching centrale.
    """
    selected_stores = list(
        stores
        if stores is not None
        else scent_main.STORES
    )

    started = time.perf_counter()
    report: Dict[str, Any] = {
        "query": query,
        "diagnostic_version": "global-endpoint-v2",
        "timing": {
            "started_at": time.time(),
            "global_duration_ms": None,
            "global_timeout_s": DIAGNOSTIC_GLOBAL_TIMEOUT,
            "store_timeout_s": DIAGNOSTIC_STORE_TIMEOUT,
        },
        "contract_audit": audit_contract(),
        "stores": {},
        "global_summary": {},
    }

    # Tutti gli store partono insieme. In questo modo il diagnostico può
    # rivelare problemi di concorrenza/timeout che una scansione sequenziale
    # nasconderebbe.
    # Un solo pool per tutti gli store. Non creiamo un executor annidato per
    # ogni store: un worker che resta bloccato non deve poter trattenere la
    # risposta HTTP oltre il limite globale del diagnostico.
    executor = ThreadPoolExecutor(
        max_workers=max(1, len(selected_stores)),
        thread_name_prefix="scent_diagnostic_store",
    )

    futures = {
        executor.submit(run_store, store, query): store
        for store in selected_stores
    }

    completed_stores = set()
    timed_out_stores = set()
    global_deadline = started + DIAGNOSTIC_GLOBAL_TIMEOUT
    store_deadlines = {
        store: started + DIAGNOSTIC_STORE_TIMEOUT
        for store in selected_stores
    }

    try:
        # Polling leggero invece di as_completed(): ci permette di distinguere
        # il timeout del singolo store dal timeout globale senza creare thread
        # executor annidati.
        pending = set(futures)
        while pending:
            now = time.perf_counter()
            if now >= global_deadline:
                break

            for future in list(pending):
                store = futures[future]
                if future.done():
                    pending.remove(future)
                    try:
                        report["stores"][store] = future.result()
                        completed_stores.add(store)
                    except Exception as exc:
                        report["stores"][store] = {
                            "store": store,
                            "status": "worker_error",
                            "errors": [{
                                "stage": "diagnostic_worker",
                                "error": f"{type(exc).__name__}: {exc}",
                                "traceback": traceback.format_exc(),
                            }],
                            "timing": {"duration_ms": None},
                            "summary": {
                                "attempt_count": 0,
                                "raw_total": 0,
                                "unique_after_dedup": 0,
                                "duplicates_removed": 0,
                                "matched_total": 0,
                                "non_matched_total": 0,
                                "error_total": 1,
                            },
                        }
                        completed_stores.add(store)
                    continue

                if store not in timed_out_stores and now >= store_deadlines[store]:
                    timed_out_stores.add(store)
                    report["stores"][store] = {
                        "store": store,
                        "status": "store_timeout",
                        "errors": [{
                            "stage": "diagnostic_store_timeout",
                            "error": (
                                f"Store non terminato entro "
                                f"{DIAGNOSTIC_STORE_TIMEOUT:.1f}s"
                            ),
                        }],
                        "timing": {
                            "duration_ms": DIAGNOSTIC_STORE_TIMEOUT * 1000,
                        },
                        "summary": {
                            "attempt_count": 0,
                            "raw_total": 0,
                            "unique_after_dedup": 0,
                            "duplicates_removed": 0,
                            "matched_total": 0,
                            "non_matched_total": 0,
                            "error_total": 1,
                        },
                    }

            if not pending:
                break
            time.sleep(0.05)

        # Tutti gli store ancora in esecuzione hanno superato il limite globale.
        # La risposta viene chiusa comunque: il diagnostico non deve mai
        # trasformarsi in una richiesta HTTP appesa.
        for future in pending:
            store = futures[future]
            if store in completed_stores or store in timed_out_stores:
                continue
            timed_out_stores.add(store)
            report["stores"][store] = {
                "store": store,
                "status": "diagnostic_timeout",
                "errors": [{
                    "stage": "diagnostic_global_timeout",
                    "error": (
                        f"Store non terminato entro "
                        f"{DIAGNOSTIC_GLOBAL_TIMEOUT:.1f}s"
                    ),
                }],
                "timing": {
                    "duration_ms": round(
                        (time.perf_counter() - started) * 1000,
                        1,
                    ),
                },
                "summary": {
                    "attempt_count": 0,
                    "raw_total": 0,
                    "unique_after_dedup": 0,
                    "duplicates_removed": 0,
                    "matched_total": 0,
                    "non_matched_total": 0,
                    "error_total": 1,
                },
            }
    finally:
        # Non aspettare mai worker che hanno superato il timeout. Il loro
        # risultato non e' piu' necessario alla risposta diagnostica.
        for future in futures:
            if not future.done():
                future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)



def print_report(
    report: Dict[str, Any],
) -> None:
    print()
    print("=" * 80)
    print("SCENTHUNTER - 5 PHASE PIPELINE DIAGNOSTIC")
    print("=" * 80)
    print(f"QUERY: {report['query']}")
    print()

    audit = report.get(
        "contract_audit",
        {},
    )

    print(
        f"PHASE 1 - CONTRACT AUDIT: "
        f"{audit.get('status', 'UNKNOWN')}"
    )

    for check in audit.get(
        "checks",
        [],
    ):
        print(
            f"  - {check.get('check')}: "
            f"{check.get('value')}"
        )

    summary = report["global_summary"]

    print()
    print("PIPELINE TOTALS")
    print(
        f"  Raw                         : "
        f"{summary['raw_total']}"
    )
    print(
        f"  Unici dopo dedup            : "
        f"{summary['unique_after_dedup']}"
    )
    print(
        f"  Duplicati rimossi           : "
        f"{summary['duplicates_removed']}"
    )
    print(
        f"  Accettati da matches()      : "
        f"{summary['matched_total']}"
    )
    print(
        f"  Rifiutati da matches()      : "
        f"{summary['non_matched_total']}"
    )
    print(
        f"  Errori                      : "
        f"{summary['errors']}"
    )

    print()
    print("PHASE 5 - REJECTION DIAGNOSTICS")
    reasons = summary.get(
        "rejection_reasons",
        {},
    )

    if not reasons:
        print("  Nessun rifiuto diagnosticato.")
    else:
        for reason, count in reasons.items():
            print(
                f"  - {reason}: {count}"
            )

    for store, store_report in report["stores"].items():
        store_summary = store_report.get(
            "summary",
            {},
        )

        print()
        print("-" * 80)
        print(f"STORE: {store}")
        timing = store_report.get("timing", {})
        print(
            f"  Status={store_report.get('status', '-') } "
            f"Time={timing.get('duration_ms', '-') }ms "
            f"Raw={store_summary.get('raw_total', 0)} "
            f"Unique={store_summary.get('unique_after_dedup', 0)} "
            f"Duplicates={store_summary.get('duplicates_removed', 0)} "
            f"Matched={store_summary.get('matched_total', 0)} "
            f"Rejected={store_summary.get('non_matched_total', 0)} "
            f"Errors={store_summary.get('error_total', 0)}"
        )

        if store_report.get(
            "raw_by_attempt"
        ):
            print("  DISCOVERY:")
            for attempt in store_report[
                "raw_by_attempt"
            ]:
                print(
                    f"    {attempt.get('attempt')!r}: "
                    f"{attempt.get('count', 0)} raw "
                    f"({attempt.get('duration_ms', '-')}ms)"
                )

        rejected = store_report.get(
            "non_matched_candidates",
            [],
        )

        if rejected:
            print("  REJECTED CANDIDATES:")
            for candidate in rejected[:20]:
                diagnostic = candidate.get(
                    "rejection_diagnostic",
                    {},
                )
                print(
                    f"    - {candidate.get('name') or '-'} "
                    f"| reasons={diagnostic.get('reasons', [])}"
                )

        resolved = [
            candidate
            for candidate in store_report.get(
                "matched_candidates",
                [],
            )
            if candidate.get(
                "resolved_identity"
            )
        ]

        if resolved:
            print("  RESOLVED IDENTITIES:")
            for candidate in resolved[:20]:
                identity = candidate[
                    "resolved_identity"
                ]
                print(
                    f"    - {candidate.get('name') or '-'} "
                    f"=> {identity.get('canonical_name') or '-'} "
                    f"| family_id={identity.get('family_id') or '-'}"
                )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnostica generica delle cinque fasi "
            "matcher/indexer ScentHunter."
        )
    )

    parser.add_argument(
        "query",
        help="Query reale da diagnosticare",
    )

    parser.add_argument(
        "--stores",
        nargs="+",
        default=None,
        help="Limita il test agli store indicati",
    )

    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help="File JSON del report",
    )

    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Non stampa il report testuale",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    report = run_query(
        args.query,
        stores=args.stores,
    )

    output_path = os.path.abspath(
        args.output
    )

    with open(
        output_path,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            report,
            file,
            ensure_ascii=False,
            indent=2,
        )

    if not args.json_only:
        print_report(report)

    print(
        f"\nReport JSON: {output_path}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
