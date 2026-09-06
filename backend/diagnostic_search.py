"""
ScentHunter progressive disappearance diagnostic (2 waves x 4 stores).

This file DOES NOT change production search logic.
It reproduces the exact progressive wave/validation/final-preparation path
used by backend/main.py and reports the state after every store completion.

Endpoint already present in main.py:
    /diagnose-deloox-disappearance?q=liquid%20brun

It specifically answers:
- did the store enter raw discovery?
- did validation accept it?
- was it present after each progressive wave?
- did _prepare_final_results remove it?
- which exact store/URL/size caused the disappearance?
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

import main_legacy as legacy
import main as production
from search_engine import SearchEngine


ENGINE = production._engine
STORES = list(ENGINE.stores)


def _safe_item(item: Any) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {"type": type(item).__name__, "value": repr(item)[:500]}

    source = item.get("source")
    source_name = source.get("source_name") if isinstance(source, dict) else None

    size = None
    try:
        size = ENGINE._extract_candidate_size_ml(item)
    except Exception:
        pass

    return {
        "store": item.get("store") or item.get("shop") or source_name,
        "name": item.get("name") or item.get("title") or item.get("product_name"),
        "brand": item.get("brand") or item.get("source_brand"),
        "canonical_name": item.get("canonical_name"),
        "catalog_variant": item.get("catalog_variant"),
        "family_id": item.get("family_id"),
        "size_ml": item.get("size_ml", size),
        "extracted_size_ml": size,
        "price": item.get("price"),
        "price_value": item.get("price_value"),
        "availability": item.get("availability"),
        "available": item.get("available"),
        "in_stock": item.get("in_stock"),
        "url": item.get("url") or item.get("product_url"),
        "product_id": item.get("product_id") or item.get("store_product_id"),
        "sku": item.get("sku"),
    }


def _store_of(item: Dict[str, Any]) -> str:
    return str(
        item.get("store")
        or item.get("shop")
        or (
            item.get("source", {}).get("source_name")
            if isinstance(item.get("source"), dict)
            else ""
        )
        or ""
    ).strip().casefold()


def _offer_in_final(item: Dict[str, Any], final_results: List[Dict[str, Any]]) -> bool:
    store = _store_of(item)
    url = str(item.get("url") or item.get("product_url") or "").strip().casefold()
    pid = str(item.get("product_id") or item.get("store_product_id") or "").strip()
    sku = str(item.get("sku") or "").strip()

    for result in final_results:
        offers = result.get("offers") if isinstance(result, dict) else None
        pool = offers if isinstance(offers, list) and offers else [result]

        for offer in pool:
            if not isinstance(offer, dict):
                continue
            if _store_of(offer) != store:
                continue

            offer_url = str(
                offer.get("url") or offer.get("product_url") or ""
            ).strip().casefold()
            offer_pid = str(
                offer.get("product_id") or offer.get("store_product_id") or ""
            ).strip()
            offer_sku = str(offer.get("sku") or "").strip()

            if url and offer_url == url:
                return True
            if pid and offer_pid == pid:
                return True
            if sku and offer_sku == sku:
                return True

    return False


def _final_offer_list(final_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output = []

    for result in final_results:
        offers = result.get("offers") if isinstance(result, dict) else None
        pool = offers if isinstance(offers, list) and offers else [result]

        for offer in pool:
            if isinstance(offer, dict):
                output.append(_safe_item(offer))

    return output


def _store_summary(items: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        store = _store_of(item) or "unknown"
        counts[store] = counts.get(store, 0) + 1
    return counts


def _deloox_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        _safe_item(item)
        for item in items
        if _store_of(item) == "deloox"
        or "deloox" in str(item.get("url") or "").casefold()
    ]


def _orioudh_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        _safe_item(item)
        for item in items
        if _store_of(item) == "orioudh"
        or "orioudh" in str(item.get("url") or "").casefold()
    ]


def _run_store_exact(store: str, query: str) -> Any:
    """
    Use exactly the production SearchEngine store runner.

    This is the important part: discovery queries, retries, candidate
    extraction and the patched run_store boundary are all inherited from
    production.
    """
    return ENGINE._run_one_store(store, query)


def run_query(query: str, stores: List[str] | None = None) -> Dict[str, Any]:
    query = str(query or "").strip()
    if not query:
        return {
            "ok": False,
            "error": "Parametro q mancante",
            "query": query,
        }

    selected_stores = list(stores or STORES)

    started = time.monotonic()
    raw_pool: List[Dict[str, Any]] = []
    validated_pool: List[Dict[str, Any]] = []

    store_reports: Dict[str, Any] = {}
    waves: List[Dict[str, Any]] = []

    # PRODUCTION FLOW: exactly 2 waves x 4 stores.
    # The four stores in a wave run concurrently.  Validation/merge happens
    # as each future completes, but the diagnostic publishes ONE snapshot only
    # after all four stores of the wave have completed.
    wave_size = 4

    for wave_start in range(0, len(selected_stores), wave_size):
        wave = selected_stores[wave_start:wave_start + wave_size]
        wave_number = wave_start // wave_size + 1

        wave_report: Dict[str, Any] = {
            "wave": wave_number,
            "stores": list(wave),
            "execution": "parallel",
            "max_workers": len(wave),
            "store_completion_order": [],
            "store_results": [],
            "validated_pool_count_after_wave": None,
            "validated_store_counts_after_wave": None,
            "final_after_wave": None,
            "final_store_counts_after_wave": None,
            "deloox_raw_after_wave": None,
            "deloox_validated_after_wave": None,
            "deloox_final_after_wave": None,
            "orioudh_raw_after_wave": None,
            "orioudh_validated_after_wave": None,
            "orioudh_final_after_wave": None,
        }

        def run_one(store: str):
            t0 = time.monotonic()
            try:
                result = _run_store_exact(store, query)
                candidates = [
                    item
                    for item in (getattr(result, "candidates", None) or [])
                    if isinstance(item, dict)
                ]

                try:
                    validated = ENGINE._validate_candidates_only(
                        query,
                        list(candidates),
                    )
                    validation_error = None
                except Exception as exc:
                    validated = []
                    validation_error = f"{type(exc).__name__}: {exc}"

                report = {
                    "store": store,
                    "status": getattr(result, "status", None),
                    "candidate_count": len(candidates),
                    "validated_count": len(validated),
                    "elapsed_seconds": round(
                        float(getattr(result, "elapsed", time.monotonic() - t0)),
                        3,
                    ),
                    "error": getattr(result, "error", None),
                    "validation_error": validation_error,
                    "raw_candidates": [_safe_item(x) for x in candidates],
                    "validated_candidates": [_safe_item(x) for x in validated],
                }
                return store, candidates, validated, report

            except Exception as exc:
                report = {
                    "store": store,
                    "status": "exception",
                    "candidate_count": 0,
                    "validated_count": 0,
                    "elapsed_seconds": round(time.monotonic() - t0, 3),
                    "error": f"{type(exc).__name__}: {exc}",
                    "validation_error": None,
                    "raw_candidates": [],
                    "validated_candidates": [],
                }
                return store, [], [], report

        # Run all four stores concurrently, exactly like the production
        # wave model. Do not serialize the stores.
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(wave),
            thread_name_prefix="scenthunter-diagnostic",
        ) as executor:
            future_map = {
                executor.submit(run_one, store): store
                for store in wave
            }

            for future in concurrent.futures.as_completed(future_map):
                store = future_map[future]
                store_name, candidates, validated, report = future.result()

                raw_pool.extend(candidates)
                validated_pool = production._merge_monotonic_validated(
                    validated_pool,
                    validated,
                )

                store_reports.setdefault(store_name, []).append(report)
                wave_report["store_results"].append(report)
                wave_report["store_completion_order"].append(store_name)

        # IMPORTANT: one and only one final snapshot for this wave.
        try:
            final_after_wave = legacy._prepare_final_results(
                list(validated_pool),
                query,
            )
            finalization_error = None
        except Exception as exc:
            final_after_wave = []
            finalization_error = f"{type(exc).__name__}: {exc}"

        wave_report["validated_pool_count_after_wave"] = len(validated_pool)
        wave_report["validated_store_counts_after_wave"] = _store_summary(
            validated_pool
        )
        wave_report["final_after_wave"] = [
            _safe_item(x) for x in final_after_wave
        ]
        wave_report["final_store_counts_after_wave"] = _store_summary(
            _final_offer_list(final_after_wave)
        )
        wave_report["finalization_error"] = finalization_error

        wave_report["deloox_raw_after_wave"] = _deloox_items(raw_pool)
        wave_report["deloox_validated_after_wave"] = _deloox_items(
            validated_pool
        )
        wave_report["deloox_final_after_wave"] = _deloox_items(
            _final_offer_list(final_after_wave)
        )

        wave_report["orioudh_raw_after_wave"] = _orioudh_items(raw_pool)
        wave_report["orioudh_validated_after_wave"] = _orioudh_items(
            validated_pool
        )
        wave_report["orioudh_final_after_wave"] = _orioudh_items(
            _final_offer_list(final_after_wave)
        )

        wave_report["validated_missing_from_final"] = [
            _safe_item(item)
            for item in validated_pool
            if not _offer_in_final(item, final_after_wave)
        ]

        waves.append(wave_report)

    # Final exact state.
    try:
        final_results = legacy._prepare_final_results(
            list(validated_pool),
            query,
        )
        finalization_error = None
    except Exception as exc:
        final_results = []
        finalization_error = f"{type(exc).__name__}: {exc}"

    final_offers = _final_offer_list(final_results)

    # Explicit diagnosis of the disappearing-store problem.
    disappearances = []

    previous_final_stores = set()

    for wave in waves:
        current_final_stores = {
            str(x.get("store") or "").strip().casefold()
            for x in _final_offer_list(wave.get("final_after_wave") or [])
            if str(x.get("store") or "").strip()
        }

        vanished = sorted(previous_final_stores - current_final_stores)

        if vanished:
            disappearances.append({
                "after_wave": wave.get("wave"),
                "vanished_stores": vanished,
                "previous_final_stores": sorted(previous_final_stores),
                "current_final_stores": sorted(current_final_stores),
                "deloox_validated": wave.get("deloox_validated_after_wave"),
                "deloox_final": wave.get("deloox_final_after_wave"),
                "validated_missing_from_final": wave.get(
                    "validated_missing_from_final"
                ),
            })

        previous_final_stores = current_final_stores

    return {
        "ok": True,
        "diagnostic_type": "progressive_wave_exact_production_path_2x4_v2",
        "query": query,
        "stores": selected_stores,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "final": {
            "validated_pool_count": len(validated_pool),
            "validated_store_counts": _store_summary(validated_pool),
            "final_result_count": len(final_results),
            "final_store_counts": _store_summary(final_offers),
            "final_offers": final_offers,
            "deloox": _deloox_items(final_offers),
            "orioudh": _orioudh_items(final_offers),
            "finalization_error": finalization_error,
        },
        "disappearance_events": disappearances,
        "waves": waves,
        "store_reports": store_reports,
    }
