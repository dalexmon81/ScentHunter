"""
ScentHunter - Deloox progressive disappearance diagnostic.

READ-ONLY diagnostic. It does not alter normal search behavior.

It reproduces the production SearchEngine.run_job pattern:
- stores are processed in waves of two;
- after each completed store the accumulated raw pool is revalidated;
- the validated pool is passed through the same final preparation;
- every progressive final snapshot is recorded;
- Deloox is compared between consecutive snapshots.

Endpoint:
    /diagnose-deloox-disappearance?q=liquid%20brun
"""

from __future__ import annotations

import concurrent.futures
import time
from typing import Any, Dict, List


def _identity(item: Dict[str, Any]) -> str:
    """Stable identity for detecting disappearance between snapshots."""
    store = str(item.get("store") or "").strip().casefold()
    url = str(item.get("url") or "").strip().casefold()
    if store or url:
        return f"store={store}|url={url}"

    product_id = str(item.get("product_id") or "").strip().casefold()
    sku = str(item.get("sku") or "").strip().casefold()
    size = item.get("size_ml")
    name = str(
        item.get("canonical_name")
        or item.get("name")
        or item.get("title")
        or ""
    ).strip().casefold()

    return f"store={store}|product_id={product_id}|sku={sku}|size={size}|name={name}"


def _is_deloox(item: Dict[str, Any]) -> bool:
    return str(item.get("store") or "").strip().casefold() == "deloox"


def _deloox_from_final(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extract Deloox offers from the exact final-result shape.

    The finalizer can place offers inside a representative product's
    ``offers`` list, so inspect both top-level products and nested offers.
    """
    found: List[Dict[str, Any]] = []
    seen = set()

    def add(item: Any) -> None:
        if not isinstance(item, dict):
            return
        if not _is_deloox(item):
            return
        key = _identity(item)
        if key in seen:
            return
        seen.add(key)
        found.append(item)

    for result in results or []:
        add(result)

        offers = result.get("offers")
        if isinstance(offers, list):
            for offer in offers:
                add(offer)

    return found


def _short(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "store": item.get("store"),
        "name": item.get("name"),
        "canonical_name": item.get("canonical_name"),
        "url": item.get("url"),
        "product_id": item.get("product_id"),
        "sku": item.get("sku"),
        "size_ml": item.get("size_ml"),
        "price": item.get("price"),
        "available": item.get("available"),
        "availability": item.get("availability"),
        "family_id": item.get("family_id"),
        "family_name": item.get("family_name"),
        "catalog_variant": item.get("catalog_variant"),
        "match_method": item.get("match_method"),
    }


def _prepare(legacy: Any, engine: Any, validated: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    """Run the same final preparation used by the production status path."""
    prepare = getattr(legacy, "_prepare_final_results", None)
    if callable(prepare):
        try:
            final = prepare(validated, query)
        except TypeError:
            final = prepare(validated)
    else:
        final = validated

    if final is None:
        final = []
    elif not isinstance(final, list):
        final = list(final)

    stable = getattr(engine, "_stable_results", None)
    if callable(stable):
        final = stable([x for x in final if isinstance(x, dict)])
    else:
        final = [x for x in final if isinstance(x, dict)]

    return final


def _stage(
    legacy: Any,
    engine: Any,
    query: str,
    raw_pool: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Create one exact progressive validation/finalization snapshot."""
    validated = engine._validate_candidates_only(query, raw_pool)
    if validated is None:
        validated = []
    validated = [x for x in validated if isinstance(x, dict)]

    final = _prepare(legacy, engine, validated, query)

    raw_deloox = [x for x in raw_pool if _is_deloox(x)]
    validated_deloox = [x for x in validated if _is_deloox(x)]
    final_deloox = _deloox_from_final(final)

    raw_keys = {_identity(x) for x in raw_deloox}
    validated_keys = {_identity(x) for x in validated_deloox}
    final_keys = {_identity(x) for x in final_deloox}

    return {
        "raw_deloox_count": len(raw_deloox),
        "validated_deloox_count": len(validated_deloox),
        "final_deloox_count": len(final_deloox),
        "raw_to_validation_lost": sorted(raw_keys - validated_keys),
        "validation_to_final_lost": sorted(validated_keys - final_keys),
        "raw_deloox": [_short(x) for x in raw_deloox],
        "validated_deloox": [_short(x) for x in validated_deloox],
        "final_deloox": [_short(x) for x in final_deloox],
        "final_result_count": len(final),
    }


def run_query(query: str = "liquid brun") -> Dict[str, Any]:
    """
    Run the progressive diagnostic against the production SearchEngine
    implementation loaded by main.py.
    """
    query = str(query or "").strip()
    if not query:
        query = "liquid brun"

    started = time.monotonic()

    try:
        # main.py has already loaded main_legacy and constructed _engine.
        import main as production

        legacy = production._legacy
        engine = production._engine

        original_stores = list(engine.stores)
        stores = list(original_stores)

        raw_pool: List[Dict[str, Any]] = []
        snapshots: List[Dict[str, Any]] = []
        disappearance_events: List[Dict[str, Any]] = []
        previous_final_keys: set[str] = set()

        # Match SearchEngine.run_job exactly: two stores per wave.
        for wave_start in range(0, len(stores), 2):
            wave = stores[wave_start : wave_start + 2]

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=2,
                thread_name_prefix="deloox-diagnostic",
            ) as executor:
                future_map = {
                    executor.submit(engine._run_one_store, store, query): store
                    for store in wave
                }

                for future in concurrent.futures.as_completed(future_map):
                    store = future_map[future]

                    try:
                        result = future.result()
                    except Exception as exc:
                        snapshots.append({
                            "after_store": store,
                            "store_status": "exception",
                            "store_error": f"{type(exc).__name__}: {exc}",
                            "stage": _stage(legacy, engine, query, raw_pool),
                        })
                        continue

                    candidates = list(result.candidates or [])
                    raw_pool.extend(
                        x for x in candidates if isinstance(x, dict)
                    )

                    stage = _stage(legacy, engine, query, raw_pool)

                    current_final_keys = {
                        _identity(x) for x in stage["final_deloox"]
                    }

                    if previous_final_keys:
                        vanished = sorted(
                            previous_final_keys - current_final_keys
                        )
                        appeared = sorted(
                            current_final_keys - previous_final_keys
                        )

                        if vanished:
                            disappearance_events.append({
                                "after_store": store,
                                "vanished_keys": vanished,
                                "appeared_keys": appeared,
                                "previous_final_deloox": [
                                    x for x in snapshots[-1]["stage"]["final_deloox"]
                                ],
                                "current_final_deloox": [
                                    x for x in stage["final_deloox"]
                                ],
                            })

                    previous_final_keys = current_final_keys

                    snapshots.append({
                        "after_store": store,
                        "store_status": result.status,
                        "store_elapsed_seconds": round(result.elapsed, 3),
                        "store_error": result.error,
                        "store_candidate_count": len(candidates),
                        "accumulated_raw_candidate_count": len(raw_pool),
                        "stage": stage,
                    })

        # A final independent stage is useful to prove whether the last
        # progressive snapshot agrees with a final re-run on the same pool.
        final_stage = _stage(legacy, engine, query, raw_pool)

        final_keys = {
            _identity(x) for x in final_stage["final_deloox"]
        }

        if not snapshots:
            conclusion = "no_snapshots"
        elif disappearance_events:
            conclusion = "deloox_disappears_between_progressive_backend_snapshots"
        elif final_stage["final_deloox_count"] == 0:
            conclusion = "deloox_missing_from_final_backend_payload"
        else:
            conclusion = "backend_keeps_deloox_through_progressive_final_snapshots"

        return {
            "ok": True,
            "diagnostic_type": "deloox_progressive_backend_v1",
            "query": query,
            "conclusion": conclusion,
            "definition": {
                "RAW": "candidate is present in accumulated raw store output",
                "VALIDATED": "candidate survives central validation",
                "FINAL": "Deloox offer is present in the exact final-result preparation",
                "DISAPPEARANCE": "a Deloox final identity present in one snapshot is absent in the next",
            },
            "stores": stores,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "raw_candidate_count": len(raw_pool),
            "snapshots": snapshots,
            "disappearance_events": disappearance_events,
            "final_recheck": final_stage,
            "final_recheck_deloox_keys": sorted(final_keys),
        }

    except Exception as exc:
        return {
            "ok": False,
            "diagnostic_type": "deloox_progressive_backend_v1",
            "query": query,
            "error": f"{type(exc).__name__}: {exc}",
        }
