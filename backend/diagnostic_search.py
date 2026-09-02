"""
ScentHunter diagnostic endpoint adapter.

The existing main.py already exposes GET /diagnostic-search and imports this
module dynamically.  It expects a callable named run_query(query, stores=...).

This module uses the SAME SearchEngine as production, so diagnostics do not
run a second, different search implementation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import main_legacy as legacy
from search_engine import SearchEngine


ENGINE = SearchEngine(legacy)


def run_query(
    query: str,
    stores: Optional[List[str]] = None,
) -> Dict[str, Any]:
    query = str(query or "").strip()

    if not query:
        return {
            "query": query,
            "ok": False,
            "error": "Parametro q mancante",
        }

    # Respect an optional store selection without modifying the production
    # engine's configured store list permanently.
    original_stores = ENGINE.stores
    if stores:
        ENGINE.stores = list(stores)

    try:
        analysis = ENGINE.analyze_query(query)
        run = ENGINE._run_stores(analysis["raw"])

        raw_pool: List[Dict[str, Any]] = []
        store_report: Dict[str, Any] = {}

        for store in ENGINE.stores:
            result = run["stores"][store]
            raw_pool.extend(result.candidates)

            store_report[store] = {
                "status": result.status,
                "candidate_count": len(result.candidates),
                "elapsed_seconds": round(result.elapsed, 3),
                "error": result.error,
            }

        final_results = ENGINE._validate_and_finalize(
            analysis["raw"],
            raw_pool,
        )

        return {
            "query": analysis,
            "ok": True,
            "research": {
                "elapsed_seconds": round(run["elapsed"], 3),
                "store_count": len(ENGINE.stores),
                "raw_candidate_count": len(raw_pool),
                "final_result_count": len(final_results),
            },
            "stores": store_report,
            "results": final_results,
        }

    except Exception as exc:
        return {
            "query": query,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    finally:
        ENGINE.stores = original_stores
