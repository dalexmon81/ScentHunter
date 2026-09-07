"""
ScentHunter - diagnostic search endpoint.

Compatible with the current SearchEngine implementation.

Pipeline inspected:

STORE
  -> RAW
  -> VALIDATED
  -> LEGACY PREPARE
  -> RECONCILIATION
  -> FINAL

This module is diagnostic only.
It does not modify SearchEngine or production search behaviour.
"""

from __future__ import annotations

import json
import traceback
from typing import Any, Dict, List, Tuple

import main_legacy as legacy
from search_engine import SearchEngine


ENGINE = SearchEngine(legacy)


# ---------------------------------------------------------------------------
# Safe helpers
# ---------------------------------------------------------------------------

def _safe(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {
            str(k): _safe(v)
            for k, v in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [_safe(v) for v in value]

    try:
        return str(value)
    except Exception:
        return repr(value)


def _store(item: Dict[str, Any], fallback: str = "") -> str:
    return str(
        item.get("store")
        or item.get("shop")
        or item.get("source")
        or fallback
        or ""
    ).strip().casefold()


def _url(item: Dict[str, Any]) -> str:
    return str(item.get("url") or "").strip()


def _product_id(item: Dict[str, Any]) -> str:
    return str(
        item.get("store_variant_id")
        or item.get("variant_id")
        or item.get("store_product_id")
        or item.get("product_id")
        or item.get("catalog_id")
        or item.get("gtin")
        or item.get("ean")
        or item.get("ean13")
        or item.get("sku")
        or ""
    ).strip()


def _name(item: Dict[str, Any]) -> str:
    return str(
        item.get("canonical_name")
        or item.get("catalog_variant")
        or item.get("product_name")
        or item.get("title")
        or item.get("name")
        or ""
    ).strip()


def _brand(item: Dict[str, Any]) -> str:
    return str(
        item.get("canonical_brand")
        or item.get("brand")
        or item.get("source_brand")
        or ""
    ).strip()


def _size(engine: SearchEngine, item: Dict[str, Any]) -> Any:
    try:
        return engine._size_ml(item)
    except Exception:
        return None


def _fingerprint(engine: SearchEngine, item: Dict[str, Any]) -> Tuple[str, ...]:
    try:
        return engine._candidate_key(item, _store(item))
    except Exception:
        return (
            _store(item),
            _product_id(item) or _url(item) or _name(item),
            str(_size(engine, item) or ""),
        )


def _offer_fingerprint(
    engine: SearchEngine,
    item: Dict[str, Any],
) -> Tuple[str, ...]:
    try:
        return engine._offer_identity(item)
    except Exception:
        return (
            _store(item),
            _product_id(item) or _url(item),
            str(_size(engine, item) or ""),
        )


def _short(engine: SearchEngine, item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "store": _store(item),
        "brand": _brand(item),
        "name": _name(item),
        "size_ml": _size(engine, item),
        "price": item.get("price_num")
        if item.get("price_num") is not None
        else item.get("price_value")
        if item.get("price_value") is not None
        else item.get("price"),
        "availability": item.get("availability")
        or item.get("stock_status")
        or item.get("stock"),
        "in_stock": item.get("in_stock"),
        "product_id": _product_id(item),
        "url": _url(item),
        "fingerprint": list(_fingerprint(engine, item)),
    }


def _contains_same_offer(
    engine: SearchEngine,
    candidate: Dict[str, Any],
    final_results: List[Dict[str, Any]],
) -> bool:
    wanted = _offer_fingerprint(engine, candidate)

    for result in final_results:
        if not isinstance(result, dict):
            continue

        offers = result.get("offers")

        if isinstance(offers, list):
            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                if _offer_fingerprint(engine, offer) == wanted:
                    return True

        # Also support standalone results.
        if _offer_fingerprint(engine, result) == wanted:
            return True

    return False


def _flatten_final_offers(
    engine: SearchEngine,
    final_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    offers: List[Dict[str, Any]] = []

    for result in final_results:
        if not isinstance(result, dict):
            continue

        nested = result.get("offers")

        if isinstance(nested, list):
            for offer in nested:
                if isinstance(offer, dict):
                    offers.append(dict(offer))
        else:
            offers.append(dict(result))

    return offers


def _stores_from_items(items: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}

    for item in items:
        if not isinstance(item, dict):
            continue

        store = _store(item)

        if not store:
            store = "_missing_store"

        counts[store] = counts.get(store, 0) + 1

    return dict(sorted(counts.items()))


def _stores_from_final(
    engine: SearchEngine,
    results: List[Dict[str, Any]],
) -> Dict[str, int]:
    return _stores_from_items(
        _flatten_final_offers(engine, results)
    )


def _result_store_details(
    engine: SearchEngine,
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []

    for result in results:
        if not isinstance(result, dict):
            continue

        offers = result.get("offers")

        if isinstance(offers, list):
            stores = []
            offer_details = []

            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                store = _store(offer)

                if store and store not in stores:
                    stores.append(store)

                offer_details.append(
                    _short(engine, offer)
                )

            output.append({
                "result_name": _name(result),
                "result_brand": _brand(result),
                "stores": stores,
                "offer_count": len(offer_details),
                "offers": offer_details,
            })

        else:
            output.append({
                "result_name": _name(result),
                "result_brand": _brand(result),
                "stores": [_store(result)] if _store(result) else [],
                "offer_count": 1,
                "offers": [_short(engine, result)],
            })

    return output


def _missing_validated_from_legacy(
    engine: SearchEngine,
    validated: List[Dict[str, Any]],
    legacy_prepared: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    missing = []

    for candidate in validated:
        if not isinstance(candidate, dict):
            continue

        if not _contains_same_offer(
            engine,
            candidate,
            legacy_prepared,
        ):
            missing.append(_short(engine, candidate))

    return missing


def _missing_validated_from_final(
    engine: SearchEngine,
    validated: List[Dict[str, Any]],
    final_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    missing = []

    for candidate in validated:
        if not isinstance(candidate, dict):
            continue

        if not _contains_same_offer(
            engine,
            candidate,
            final_results,
        ):
            missing.append(_short(engine, candidate))

    return missing


def _raw_by_store(
    engine: SearchEngine,
    store_runs: Dict[str, Any],
) -> Dict[str, List[Dict[str, Any]]]:
    output: Dict[str, List[Dict[str, Any]]] = {}

    for store, result in store_runs.items():
        candidates = getattr(result, "candidates", None)

        if not isinstance(candidates, list):
            candidates = []

        output[store] = [
            dict(item)
            for item in candidates
            if isinstance(item, dict)
        ]

    return output


def _status_by_store(
    store_runs: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    output: Dict[str, Dict[str, Any]] = {}

    for store, result in store_runs.items():
        output[store] = {
            "status": getattr(result, "status", None),
            "count": len(
                getattr(result, "candidates", None) or []
            ),
            "elapsed": getattr(result, "elapsed", None),
            "error": getattr(result, "error", None),
        }

    return output


def _validated_by_store(
    engine: SearchEngine,
    validated: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    output: Dict[str, List[Dict[str, Any]]] = {}

    for item in validated:
        if not isinstance(item, dict):
            continue

        store = _store(item) or "_missing_store"

        output.setdefault(store, []).append(
            _short(engine, item)
        )

    return output


def _raw_details_by_store(
    engine: SearchEngine,
    raw_by_store: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, List[Dict[str, Any]]]:
    output: Dict[str, List[Dict[str, Any]]] = {}

    for store, candidates in raw_by_store.items():
        output[store] = [
            _short(engine, item)
            for item in candidates
        ]

    return output


def _infer_rejection_reason(
    engine: SearchEngine,
    item: Dict[str, Any],
    query: str,
) -> List[str]:
    reasons: List[str] = []

    name = _name(item)
    brand = _brand(item)

    normalized_query = engine._norm(query)
    normalized_name = engine._norm(name)
    normalized_brand = engine._norm(brand)

    if not name:
        reasons.append("missing_product_name")

    if normalized_query and normalized_name:
        query_tokens = {
            token
            for token in normalized_query.split()
            if len(token) > 1
        }

        name_tokens = set(normalized_name.split())

        if query_tokens and not query_tokens.intersection(name_tokens):
            reasons.append("query_name_token_mismatch")

    if brand:
        if (
            normalized_brand
            and normalized_query
            and normalized_brand not in normalized_query
            and not normalized_name
        ):
            reasons.append("brand_not_obvious")

    size = _size(engine, item)

    if size is None:
        # This is only diagnostic information.
        # The normalizer intentionally does not infer size.
        reasons.append("size_not_detected")

    availability = str(
        item.get("availability")
        or item.get("stock_status")
        or item.get("stock")
        or ""
    ).strip().casefold()

    if availability in {
        "out_of_stock",
        "oos",
        "unavailable",
        "sold_out",
        "sold out",
        "false",
        "0",
        "out of stock",
    }:
        reasons.append("out_of_stock_candidate")

    return reasons


# ---------------------------------------------------------------------------
# Main diagnostic
# ---------------------------------------------------------------------------

def run_query(
    query: str,
    stores: Any = None,
) -> Dict[str, Any]:
    """
    Execute one complete diagnostic search.

    Validation is performed exactly through the method that exists in the
    current SearchEngine:

        ENGINE._validate_batch(query, candidates)

    No call to a non-existent validation method is made.
    """

    text = str(query or "").strip()

    if not text:
        return {
            "ok": False,
            "query": "",
            "error": "empty query",
        }

    original_stores = list(ENGINE.stores)

    try:
        # Optional store filter for focused diagnosis.
        if stores:
            if isinstance(stores, str):
                requested = [
                    x.strip().casefold()
                    for x in stores.split(",")
                    if x.strip()
                ]
            elif isinstance(stores, (list, tuple, set)):
                requested = [
                    str(x).strip().casefold()
                    for x in stores
                    if str(x).strip()
                ]
            else:
                requested = []

            if requested:
                ENGINE.stores = [
                    store
                    for store in original_stores
                    if store.casefold() in requested
                ]

        analysis = ENGINE.analyze_query(text)

        # ---------------------------------------------------------------
        # 1. STORE EXECUTION
        # ---------------------------------------------------------------

        run = ENGINE._run_stores(
            analysis["raw"]
        )

        store_runs = run.get("stores", {})

        raw_by_store = _raw_by_store(
            ENGINE,
            store_runs,
        )

        raw_pool: List[Dict[str, Any]] = []

        for store in ENGINE.stores:
            for item in raw_by_store.get(store, []):
                candidate = dict(item)

                if not candidate.get("store") and not candidate.get("shop"):
                    candidate["store"] = store

                raw_pool.append(candidate)

        # Deduplicate RAW exactly with the production engine key.
        raw_unique: List[Dict[str, Any]] = []
        raw_seen = set()

        for item in raw_pool:
            key = _fingerprint(
                ENGINE,
                item,
            )

            if key in raw_seen:
                continue

            raw_seen.add(key)
            raw_unique.append(item)

        # ---------------------------------------------------------------
        # 2. VALIDATION
        # ---------------------------------------------------------------
        #
        # This is the actual validation method available in the current
        # search_engine.py supplied by the user.
        #
        # It is intentionally called ONCE for the diagnostic batch.
        # ---------------------------------------------------------------

        validated = ENGINE._validate_batch(
            analysis["raw"],
            raw_unique,
        )

        validated = [
            dict(item)
            for item in validated
            if isinstance(item, dict)
        ]

        # ---------------------------------------------------------------
        # 3. LEGACY FINAL PREPARATION
        # ---------------------------------------------------------------

        legacy_prepare = getattr(
            legacy,
            "_prepare_final_results",
            None,
        )

        if callable(legacy_prepare):
            try:
                legacy_prepared = legacy_prepare(
                    list(validated),
                    text,
                )
            except TypeError:
                legacy_prepared = legacy_prepare(
                    list(validated)
                )
        else:
            legacy_prepared = list(validated)

        if legacy_prepared is None:
            legacy_prepared = []

        if not isinstance(legacy_prepared, list):
            try:
                legacy_prepared = list(legacy_prepared)
            except Exception:
                legacy_prepared = []

        legacy_prepared = [
            dict(item)
            for item in legacy_prepared
            if isinstance(item, dict)
        ]

        # ---------------------------------------------------------------
        # 4. PRODUCTION RECONCILIATION
        # ---------------------------------------------------------------
        #
        # Mirror SearchEngine._prepare_final() AFTER the legacy preparation,
        # without executing legacy preparation for a second time.
        # ---------------------------------------------------------------

        reconciled = ENGINE._reconcile_prepared(
            list(legacy_prepared),
            list(validated),
        )

        final_results = ENGINE._stable_results(
            reconciled
        )

        # ---------------------------------------------------------------
        # 5. LOSS ANALYSIS
        # ---------------------------------------------------------------

        raw_fingerprints = {
            _fingerprint(ENGINE, item)
            for item in raw_unique
        }

        validated_fingerprints = {
            _fingerprint(ENGINE, item)
            for item in validated
        }

        raw_not_validated = []

        for item in raw_unique:
            key = _fingerprint(
                ENGINE,
                item,
            )

            if key not in validated_fingerprints:
                raw_not_validated.append({
                    **_short(ENGINE, item),
                    "possible_rejection_reasons": (
                        _infer_rejection_reason(
                            ENGINE,
                            item,
                            text,
                        )
                    ),
                })

        validated_not_in_legacy = _missing_validated_from_legacy(
            ENGINE,
            validated,
            legacy_prepared,
        )

        validated_not_in_final = _missing_validated_from_final(
            ENGINE,
            validated,
            final_results,
        )

        # ---------------------------------------------------------------
        # 6. STORE-LEVEL SUMMARY
        # ---------------------------------------------------------------

        status_by_store = _status_by_store(
            store_runs
        )

        raw_store_counts = _stores_from_items(
            raw_unique
        )

        validated_store_counts = _stores_from_items(
            validated
        )

        legacy_store_counts = _stores_from_final(
            ENGINE,
            legacy_prepared,
        )

        final_store_counts = _stores_from_final(
            ENGINE,
            final_results,
        )

        raw_by_store_details = _raw_details_by_store(
            ENGINE,
            raw_by_store,
        )

        validated_details = _validated_by_store(
            ENGINE,
            validated,
        )

        # ---------------------------------------------------------------
        # 7. EXACT STORE FLOW
        # ---------------------------------------------------------------

        store_flow: Dict[str, Dict[str, Any]] = {}

        all_stores = list(dict.fromkeys(
            list(ENGINE.stores)
            + list(raw_store_counts.keys())
            + list(validated_store_counts.keys())
            + list(final_store_counts.keys())
        ))

        for store in all_stores:
            raw_items = raw_by_store.get(store, [])

            raw_count = len(raw_items)

            validated_count = sum(
                1
                for item in validated
                if _store(item, store) == store.casefold()
            )

            legacy_count = sum(
                1
                for item in _flatten_final_offers(
                    ENGINE,
                    legacy_prepared,
                )
                if _store(item) == store.casefold()
            )

            final_count = sum(
                1
                for item in _flatten_final_offers(
                    ENGINE,
                    final_results,
                )
                if _store(item) == store.casefold()
            )

            store_flow[store] = {
                "execution": status_by_store.get(
                    store,
                    {},
                ),
                "raw": raw_count,
                "validated": validated_count,
                "legacy_prepared": legacy_count,
                "final": final_count,
            }

        # ---------------------------------------------------------------
        # 8. HUMAN-READABLE DIAGNOSIS
        # ---------------------------------------------------------------

        if not raw_unique:
            diagnosis = (
                "NO_RAW_RESULTS: the stores did not produce candidates. "
                "Check store execution status, timeout and scraper errors."
            )
        elif not validated:
            diagnosis = (
                "VALIDATION_LOSS: candidates reached RAW but none survived "
                "the central validation stage."
            )
        elif validated_not_in_legacy:
            diagnosis = (
                "LEGACY_PREPARE_LOSS: accepted candidates disappear inside "
                "_prepare_final_results()."
            )
        elif validated_not_in_final:
            diagnosis = (
                "RECONCILIATION_LOSS: accepted candidates disappear after "
                "legacy preparation/reconciliation."
            )
        else:
            diagnosis = (
                "NO_OFFER_LOSS_DETECTED: every validated candidate reaches "
                "the final result set. If production still loses stores, "
                "inspect the API/job publication layer or store execution."
            )

        # Strong signal for the timeout/concurrency hypothesis.
        timeout_stores = [
            store
            for store, status in status_by_store.items()
            if status.get("status") == "timeout"
        ]

        empty_stores = [
            store
            for store, status in status_by_store.items()
            if status.get("status") == "empty"
        ]

        error_stores = [
            store
            for store, status in status_by_store.items()
            if status.get("status") == "error"
        ]

        return {
            "ok": True,
            "query": text,
            "diagnosis": diagnosis,

            "engine": {
                "store_timeout": ENGINE.store_timeout,
                "global_timeout": ENGINE.global_timeout,
                "stores": list(ENGINE.stores),
            },

            "timing": {
                "store_execution_elapsed": run.get("elapsed"),
            },

            "counts": {
                "raw_total": len(raw_unique),
                "validated_total": len(validated),
                "legacy_prepared_results": len(
                    legacy_prepared
                ),
                "final_results": len(final_results),
                "raw_fingerprints": len(raw_fingerprints),
                "validated_fingerprints": len(
                    validated_fingerprints
                ),
            },

            "store_flow": store_flow,

            "store_status": status_by_store,

            "store_counts": {
                "raw": raw_store_counts,
                "validated": validated_store_counts,
                "legacy_prepared": legacy_store_counts,
                "final": final_store_counts,
            },

            "execution_flags": {
                "timeout_stores": timeout_stores,
                "empty_stores": empty_stores,
                "error_stores": error_stores,
            },

            "raw_by_store": raw_by_store_details,

            "validated_by_store": validated_details,

            "raw_not_validated": raw_not_validated,

            "validated_missing_from_legacy_prepare": (
                validated_not_in_legacy
            ),

            "validated_missing_from_final": (
                validated_not_in_final
            ),

            "legacy_final_results": _result_store_details(
                ENGINE,
                legacy_prepared,
            ),

            "production_final_results": _result_store_details(
                ENGINE,
                final_results,
            ),

            "final_results": _safe(final_results),
        }

    except Exception as exc:
        return {
            "ok": False,
            "query": text,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=12),
        }

    finally:
        ENGINE.stores = original_stores


def diagnostic_json(
    query: str,
    stores: Any = None,
) -> str:
    """
    Optional helper for callers that need a JSON string.
    """
    return json.dumps(
        run_query(query, stores),
        ensure_ascii=False,
        default=str,
    )
