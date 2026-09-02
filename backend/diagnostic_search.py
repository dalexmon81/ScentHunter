"""
ScentHunter deep diagnostic adapter.

Runs the SAME production SearchEngine and exposes the complete path:
store -> raw candidates -> central validation -> final preparation.

It is intentionally diagnostic-only and does not change production search
behavior.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
import json

import main_legacy as legacy
from search_engine import SearchEngine

ENGINE = SearchEngine(legacy)


def _safe(value: Any) -> Any:
    """Keep JSON useful without dumping enormous/unserializable objects."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_safe(x) for x in value[:100]]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            # Keep diagnostic payload focused on identity/offer fields.
            if k in {
                "name", "title", "product_name", "brand", "brand_name",
                "store", "shop", "url", "source", "source_name",
                "product_id", "id", "sku", "ean", "gtin", "mpn",
                "price", "price_num", "currency", "size_ml", "size",
                "format", "concentration", "gender", "availability",
                "available", "stock", "stock_status", "in_stock",
                "canonical_name", "canonical_id", "family_id",
                "match_method", "catalog_id", "catalog_variant",
                "identity", "offers", "raw_name", "raw_title",
                "card_text", "evidence", "source_url",
            }:
                out[k] = _safe(v)
        return out
    return str(value)


def _identity_key(item: Dict[str, Any]) -> tuple:
    return (
        str(
            item.get("product_id")
            or item.get("canonical_id")
            or item.get("id")
            or item.get("sku")
            or ""
        ).strip(),
        str(item.get("url") or item.get("source_url") or "").strip(),
        str(
            item.get("name")
            or item.get("title")
            or item.get("product_name")
            or ""
        ).strip(),
        str(item.get("store") or item.get("shop") or "").strip(),
    )


def _find_survivors(raw: List[Dict[str, Any]],
                    validated: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return raw candidates that can be linked to a validated candidate."""
    keys = {_identity_key(x) for x in validated}
    survivors = []
    for item in raw:
        key = _identity_key(item)
        if key in keys:
            survivors.append(item)
            continue

        # A validator may rewrite name/id, so fall back to stable URL/product id.
        stable = (
            str(item.get("product_id") or item.get("id") or item.get("sku") or "").strip(),
            str(item.get("url") or item.get("source_url") or "").strip(),
            str(item.get("store") or item.get("shop") or "").strip(),
        )
        for other in validated:
            other_stable = (
                str(other.get("product_id") or other.get("id") or other.get("sku") or "").strip(),
                str(other.get("url") or other.get("source_url") or "").strip(),
                str(other.get("store") or other.get("shop") or "").strip(),
            )
            if stable == other_stable and any(stable):
                survivors.append(item)
                break
    return survivors


def run_query(
    query: str,
    stores: Optional[List[str]] = None,
) -> Dict[str, Any]:
    query = str(query or "").strip()
    if not query:
        return {"query": query, "ok": False, "error": "Parametro q mancante"}

    original_stores = ENGINE.stores
    if stores:
        ENGINE.stores = list(stores)

    try:
        analysis = ENGINE.analyze_query(query)
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
                "candidates": [_safe(x) for x in raw],
            }

        validated = ENGINE._validate_candidates_only(
            analysis["raw"],
            raw_pool,
        )
        final_results = ENGINE._validate_and_finalize(
            analysis["raw"],
            raw_pool,
        )

        validated_by_store: Dict[str, List[Dict[str, Any]]] = {}
        for store in ENGINE.stores:
            validated_by_store[store] = [
                _safe(x) for x in validated
                if str(x.get("store") or x.get("shop") or "").strip().lower() == store
            ]

        return {
            "ok": True,
            "query": analysis,
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
                "raw_candidates": [_safe(x) for x in raw_pool],
                "validated_candidates": [_safe(x) for x in validated],
                "final_results": [_safe(x) for x in final_results],
                "validated_by_store": validated_by_store,
                "raw_survivors_by_store": {
                    store: [_safe(x) for x in _find_survivors(raw_by_store[store], validated)]
                    for store in ENGINE.stores
                },
            },
        }

    except Exception as exc:
        return {
            "query": query,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        ENGINE.stores = original_stores
