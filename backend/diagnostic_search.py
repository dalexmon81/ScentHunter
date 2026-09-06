"""
ScentHunter - production-faithful pipeline diagnostic.

This diagnostic is deliberately different from the old deep diagnostic:
- runs the SAME SearchEngine store execution used by /search;
- validates candidates EXACTLY ONCE;
- prepares final results from that already-validated list;
- never calls validation twice;
- reports every candidate by store + URL/product id;
- explicitly classifies where an offer disappeared:
  1) scraper/discovery: never entered raw pool
  2) central validation: entered raw pool but was rejected
  3) final preparation/grouping: validated but absent from final offers
  4) final output: present in final offers

It is diagnostic-only and does not modify production search behavior.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
import re

import main_legacy as legacy
from search_engine import SearchEngine

ENGINE = SearchEngine(legacy)


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_safe(x) for x in value[:100]]
    if isinstance(value, dict):
        keep = {
            "name", "title", "product_name", "brand", "brand_name",
            "store", "shop", "url", "source", "source_name",
            "product_id", "id", "sku", "ean", "gtin", "mpn",
            "price", "price_num", "currency", "size_ml", "size",
            "format", "concentration", "gender", "availability",
            "available", "stock", "stock_status", "in_stock",
            "canonical_name", "canonical_id", "family_id", "family_name",
            "match_method", "catalog_id", "catalog_variant",
            "identity", "offers", "raw_name", "raw_title",
            "card_text", "evidence", "source_url", "raw_data",
            "attributes", "offer", "provenance",
        }
        return {k: _safe(v) for k, v in value.items() if k in keep}
    return str(value)


def _store(item: Dict[str, Any]) -> str:
    return str(item.get("store") or item.get("shop") or "").strip()


def _url(item: Dict[str, Any]) -> str:
    source = item.get("source")
    if isinstance(source, dict):
        return str(
            item.get("url")
            or item.get("source_url")
            or source.get("url")
            or ""
        ).strip()
    return str(item.get("url") or item.get("source_url") or "").strip()


def _product_id(item: Dict[str, Any]) -> str:
    identity = item.get("identity")
    if isinstance(identity, dict):
        value = identity.get("store_product_id")
        if isinstance(value, dict):
            value = value.get("value")
        if value not in (None, ""):
            return str(value).strip()

    return str(
        item.get("product_id")
        or item.get("canonical_id")
        or item.get("id")
        or ""
    ).strip()


def _sku(item: Dict[str, Any]) -> str:
    identity = item.get("identity")
    if isinstance(identity, dict):
        value = identity.get("sku")
        if isinstance(value, dict):
            value = value.get("value")
        if value not in (None, ""):
            return str(value).strip()
    return str(item.get("sku") or "").strip()


def _name(item: Dict[str, Any]) -> str:
    source = item.get("source")
    source_name = source.get("source_name") if isinstance(source, dict) else ""
    return str(
        item.get("name")
        or item.get("title")
        or item.get("product_name")
        or source_name
        or ""
    ).strip()


def _fingerprint(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stable evidence identity.

    Store + URL is the strongest link for this diagnostic. Product id/sku are
    retained as secondary evidence, but never replace the URL when present.
    """
    return {
        "store": _store(item),
        "url": _url(item),
        "product_id": _product_id(item),
        "sku": _sku(item),
        "name": _name(item),
        "canonical_name": str(item.get("canonical_name") or "").strip(),
    }


def _short(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "store": _store(item),
        "url": _url(item),
        "product_id": _product_id(item),
        "sku": _sku(item),
        "name": _name(item),
        "price": item.get("price"),
        "availability": item.get("availability"),
        "available": item.get("available"),
        "size_ml": item.get("size_ml"),
        "canonical_name": item.get("canonical_name"),
        "family_id": item.get("family_id"),
        "family_name": item.get("family_name"),
        "catalog_variant": item.get("catalog_variant"),
        "match_method": item.get("match_method"),
    }


def _offer_fingerprints(final_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for result in final_results:
        offers = result.get("offers")
        if isinstance(offers, list) and offers:
            for offer in offers:
                if isinstance(offer, dict):
                    out.append(_fingerprint(offer))
        else:
            out.append(_fingerprint(result))
    return out


def _contains_same_offer(candidate: Dict[str, Any], validated: List[Dict[str, Any]]) -> bool:
    """
    Link raw -> validated without using the candidate name as identity.

    URL+store is preferred. If URL is absent, use store+product id or store+SKU.
    """
    c_store = _store(candidate).lower()
    c_url = _url(candidate).lower()
    c_pid = _product_id(candidate)
    c_sku = _sku(candidate)

    for item in validated:
        if _store(item).lower() != c_store:
            continue

        i_url = _url(item).lower()
        i_pid = _product_id(item)
        i_sku = _sku(item)

        if c_url and i_url and c_url == i_url:
            return True
        if c_pid and i_pid and c_pid == i_pid:
            return True
        if c_sku and i_sku and c_sku == i_sku:
            return True

    return False


def _validated_to_final_map(
    validated: List[Dict[str, Any]],
    final_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    final_offers = _offer_fingerprints(final_results)

    def present(item: Dict[str, Any]) -> bool:
        store = _store(item).lower()
        url = _url(item).lower()
        pid = _product_id(item)
        sku = _sku(item)

        for offer in final_offers:
            if str(offer.get("store") or "").lower() != store:
                continue
            if url and str(offer.get("url") or "").lower() == url:
                return True
            if pid and str(offer.get("product_id") or "") == pid:
                return True
            if sku and str(offer.get("sku") or "") == sku:
                return True
        return False

    return {
        "validated_present_in_final": [
            _short(item) for item in validated if present(item)
        ],
        "validated_missing_from_final": [
            _short(item) for item in validated if not present(item)
        ],
    }


def _infer_rejection_reason(
    item: Dict[str, Any],
    query: str,
) -> Dict[str, Any]:
    """
    Best-effort deterministic clues, NOT a fake claim about the matcher.

    The actual matcher remains authoritative. These checks tell us what to
    inspect next when a raw candidate disappears.
    """
    text = " ".join(
        str(item.get(k) or "")
        for k in ("name", "title", "product_name", "canonical_name")
    )
    source = item.get("source")
    if isinstance(source, dict):
        text += " " + str(source.get("source_name") or "")
        text += " " + str(source.get("source_brand") or "")

    norm = getattr(legacy, "norm", lambda x: str(x).lower())
    q = norm(query)
    t = norm(text)

    clues: List[str] = []
    if q and not all(token in t for token in q.split() if token):
        clues.append("query_tokens_not_all_in_candidate_text")

    try:
        if getattr(legacy, "has_small_size", lambda x: False)(item):
            clues.append("small_size_or_sample_signal")
    except Exception:
        pass

    try:
        non_single = getattr(legacy, "_non_single_product_match", None)
        if non_single is not None and non_single(item, query):
            clues.append("non_single_product_or_excluded_type")
    except Exception:
        pass

    return {
        "clues": clues,
        "note": "These are diagnostic clues only; they are not substituted for the real matcher decision.",
    }


def run_query(
    query: str,
    stores: Optional[List[str]] = None,
) -> Dict[str, Any]:
    query = str(query or "").strip()
    if not query:
        return {"ok": False, "error": "Parametro q mancante", "query": query}

    original_stores = ENGINE.stores
    if stores:
        ENGINE.stores = list(stores)

    try:
        analysis = ENGINE.analyze_query(query)

        # EXACTLY the same store execution as production /search.
        run = ENGINE._run_stores(analysis["raw"])

        raw_by_store: Dict[str, List[Dict[str, Any]]] = {}
        store_report: Dict[str, Any] = {}
        raw_pool: List[Dict[str, Any]] = []

        for store in ENGINE.stores:
            result = run["stores"][store]
            raw = [x for x in result.candidates if isinstance(x, dict)]
            raw_by_store[store] = raw
            raw_pool.extend(raw)
            store_report[store] = {
                "status": result.status,
                "candidate_count": len(raw),
                "elapsed_seconds": round(result.elapsed, 3),
                "error": result.error,
                "candidates": [_short(x) for x in raw],
            }

        # EXACTLY ONCE: this is the production central validation stage.
        validated = ENGINE._validate_candidates_only(
            analysis["raw"],
            raw_pool,
        )

        # Do NOT call _validate_and_finalize here because that would validate
        # the same raw pool a second time. Prepare directly from the validated
        # list, exactly matching the second half of production.
        prepare = getattr(legacy, "_prepare_final_results", None)
        if prepare is not None:
            try:
                final_results = prepare(validated, analysis["raw"])
            except TypeError:
                final_results = prepare(validated)
        else:
            final_results = validated

        if final_results is None:
            final_results = []
        if not isinstance(final_results, list):
            final_results = list(final_results)

        final_results = ENGINE._stable_results(
            [x for x in final_results if isinstance(x, dict)]
        )

        # Build precise stage classification.
        raw_that_validated: Dict[str, List[Dict[str, Any]]] = {}
        raw_rejected: Dict[str, List[Dict[str, Any]]] = {}

        for store in ENGINE.stores:
            raw_that_validated[store] = []
            raw_rejected[store] = []

            for item in raw_by_store[store]:
                if _contains_same_offer(item, validated):
                    raw_that_validated[store].append(item)
                else:
                    raw_rejected[store].append(item)

        final_map = _validated_to_final_map(validated, final_results)

        return {
            "ok": True,
            "diagnostic_type": "production_faithful_single_pass",
            "query": analysis,
            "conclusion": {
                "definition": {
                    "DISCOVERY": "candidate entered raw store output",
                    "VALIDATION": "candidate survived central matcher exactly once",
                    "FINAL_PREPARATION": "validated candidate became an offer in final result",
                    "FINAL_OUTPUT": "offer is present in the exact final /search-equivalent payload",
                },
                "store_summary": {
                    store: {
                        "raw": len(raw_by_store[store]),
                        "validated": len(raw_that_validated[store]),
                        "rejected": len(raw_rejected[store]),
                        "final_offers": sum(
                            1 for x in _offer_fingerprints(final_results)
                            if str(x.get("store") or "").lower() == store.lower()
                        ),
                        "status": store_report[store]["status"],
                    }
                    for store in ENGINE.stores
                },
            },
            "research": {
                "elapsed_seconds": round(run["elapsed"], 3),
                "store_count": len(ENGINE.stores),
                "retried_stores": run.get("retried_stores", []),
                "raw_candidate_count": len(raw_pool),
                "validated_candidate_count": len(validated),
                "final_result_count": len(final_results),
            },
            "stores": store_report,
            "pipeline": {
                "raw_candidates_by_store": {
                    store: [_safe(x) for x in raw_by_store[store]]
                    for store in ENGINE.stores
                },
                "validated_candidates_by_store": {
                    store: [_safe(x) for x in raw_that_validated[store]]
                    for store in ENGINE.stores
                },
                "rejected_candidates_by_store": {
                    store: [
                        {
                            **_short(x),
                            "rejection_clues": _infer_rejection_reason(x, query),
                        }
                        for x in raw_rejected[store]
                    ]
                    for store in ENGINE.stores
                },
                "validated_missing_from_final": final_map["validated_missing_from_final"],
                "validated_present_in_final": final_map["validated_present_in_final"],
                "final_results": [_safe(x) for x in final_results],
            },
        }

    except Exception as exc:
        return {
            "ok": False,
            "query": query,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        ENGINE.stores = original_stores
