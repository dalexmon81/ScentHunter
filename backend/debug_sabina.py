from __future__ import annotations

"""
ScentHunter — Sabina / Born in Roma FORENSIC DIAGNOSTIC v2

IMPORTANT:
- Diagnostic only. Does NOT modify scraper.py, ProductMatcher or family_registry.
- Designed to NEVER leave the HTTP request hanging indefinitely.
- Every potentially blocking operation runs in a child process and is
  hard-killed when its timeout expires.
- The endpoint returns a finite JSON report even when a stage times out.

REGISTER ONLY THIS FILE IF YOU WANT THE ENDPOINT:
    from debug_sabina_born_in_roma_v2 import router
    app.include_router(router)

TEST:
    /diagnose-sabina-born-in-roma-v2?q=Born%20in%20Roma

The report traces:
    DISCOVERY -> EXTRACTION -> VALIDATION -> MATCHING -> DEDUP
and separately compares DIRECT SEARCH with SEARCH_STREAM.

No production behavior is changed by this module.
"""

import importlib
import json
import multiprocessing as mp
import re
import time
import traceback
from copy import deepcopy
from typing import Any, Dict, List

from fastapi import APIRouter, Query

router = APIRouter()

EXPECTED = [
    "Born in Roma Uomo",
    "Born in Roma Uomo Intense",
    "Born in Roma Uomo Extradose",
    "Born in Roma Uomo Green Stravaganza",
    "Born in Roma Uomo Coral Fantasy",
    "Born in Roma Uomo Yellow Dream",
    "Born in Roma Uomo Purple Melancholia",
    "Born in Roma Uomo The Gold",
    "Born in Roma Uomo Ivory",
    "Born in Roma Donna",
    "Born in Roma Donna Intense",
    "Born in Roma Donna Extradose",
    "Born in Roma Donna Green Stravaganza",
    "Born in Roma Donna Coral Fantasy",
    "Born in Roma Donna Yellow Dream",
    "Born in Roma Donna Purple Melancholia",
    "Born in Roma Donna The Gold",
    "Born in Roma Donna Ivory",
]

# Hard limits. The endpoint itself also has a global safety deadline.
DISCOVERY_TIMEOUT = 20
EXTRACTION_TIMEOUT = 12
SEARCH_TIMEOUT = 35
STREAM_TIMEOUT = 35
GLOBAL_TIMEOUT = 75


def _norm(v: Any) -> str:
    s = str(v or "").casefold().strip()
    s = re.sub(r"[^a-z0-9à-ÿ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _jsonable(v: Any) -> Any:
    try:
        return json.loads(json.dumps(v, ensure_ascii=False, default=str))
    except Exception:
        return str(v)


def _row_name(row: Dict[str, Any]) -> str:
    for key in ("canonical_name", "name", "title", "catalog_variant"):
        if row.get(key):
            return str(row[key])
    source = row.get("source")
    if isinstance(source, dict) and source.get("source_name"):
        return str(source["source_name"])
    return ""


def _row_evidence(row: Dict[str, Any]) -> Dict[str, Any]:
    source = row.get("source") if isinstance(row.get("source"), dict) else {}
    return {
        "name": row.get("name"),
        "canonical_name": row.get("canonical_name"),
        "catalog_variant": row.get("catalog_variant"),
        "source_name": source.get("source_name"),
        "brand": row.get("brand"),
        "url": row.get("url") or source.get("url"),
        "size_ml": row.get("size_ml"),
        "price_num": row.get("price_num"),
        "availability": row.get("availability"),
        "store_product_id": row.get("store_product_id"),
        "sku": row.get("sku"),
    }


def _match_variant(row: Dict[str, Any], expected: str) -> bool:
    target = _norm(expected)
    names = [
        row.get("name"),
        row.get("canonical_name"),
        row.get("title"),
        row.get("catalog_variant"),
    ]
    source = row.get("source")
    if isinstance(source, dict):
        names.append(source.get("source_name"))

    normalized = [_norm(x) for x in names if x]
    if target in normalized:
        return True

    # Diagnostic-only alias/order tolerance, not ProductMatcher logic.
    target_tokens = set(target.split())
    for name in normalized:
        tokens = set(name.split())
        if target_tokens and len(tokens & target_tokens) / len(target_tokens) >= 0.80:
            return True
    return False


def _variant_presence(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out = {}
    for expected in EXPECTED:
        out[expected] = [
            _row_evidence(r) for r in rows
            if isinstance(r, dict) and _match_variant(r, expected)
        ]
    return out


def _child_worker(kind: str, query: str, url: str | None, conn) -> None:
    """Run one risky operation in a killable child process."""
    try:
        sabina = importlib.import_module("scrapers.sabina.scraper")

        if kind == "discovery":
            requests = getattr(sabina, "requests", None)
            fn = getattr(sabina, "_discover_from_first_party", None)
            if requests is None or not callable(fn):
                raise RuntimeError("Sabina discovery dependencies unavailable")
            session = requests.Session()
            try:
                headers = getattr(sabina, "HEADERS", None)
                if isinstance(headers, dict):
                    session.headers.update(headers)
                result = fn(session, query)
            finally:
                session.close()
            conn.send({"ok": True, "value": list(result or [])})

        elif kind == "extract":
            fn = getattr(sabina, "_extract_product_page", None)
            if not callable(fn):
                raise RuntimeError("_extract_product_page unavailable")
            result = fn(url, query)
            conn.send({"ok": True, "value": _jsonable(list(result or []))})

        elif kind == "search":
            fn = getattr(sabina, "search", None)
            if not callable(fn):
                raise RuntimeError("search unavailable")
            result = fn(query)
            conn.send({"ok": True, "value": _jsonable(list(result or []))})

        elif kind == "stream":
            fn = getattr(sabina, "search_stream", None)
            if not callable(fn):
                conn.send({"ok": True, "value": [], "note": "search_stream unavailable"})
                return
            emitted = []

            def emit(row):
                if isinstance(row, dict):
                    emitted.append(_jsonable(row))

            result = fn(query, emit)
            if result is not None:
                try:
                    for row in result:
                        if isinstance(row, dict):
                            emitted.append(_jsonable(row))
                except TypeError:
                    pass
            conn.send({"ok": True, "value": emitted})

        else:
            raise RuntimeError(f"unknown diagnostic operation: {kind}")

    except BaseException as exc:
        conn.send({
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })
    finally:
        conn.close()


def _run_hard(kind: str, query: str, timeout: float, url: str | None = None) -> Dict[str, Any]:
    ctx = mp.get_context("fork") if "fork" in mp.get_all_start_methods() else mp.get_context()
    parent, child = ctx.Pipe(False)
    proc = ctx.Process(target=_child_worker, args=(kind, query, url, child), daemon=True)
    started = time.monotonic()
    proc.start()
    child.close()

    payload = None
    try:
        if parent.poll(timeout):
            try:
                payload = parent.recv()
            except EOFError:
                payload = {"ok": False, "error": "child exited without a result"}
        else:
            payload = {
                "ok": False,
                "timeout": True,
                "error": f"{kind} exceeded hard timeout of {timeout}s",
            }
    finally:
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=2)
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=1)
        else:
            proc.join(timeout=0.2)
        parent.close()

    elapsed = round(time.monotonic() - started, 3)
    payload = payload or {"ok": False, "error": "no diagnostic result"}
    payload["elapsed"] = elapsed
    payload["operation"] = kind
    return payload


def _load_main():
    try:
        return importlib.import_module("main")
    except Exception:
        return None


def _main_clean(rows: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
    main = _load_main()
    fn = getattr(main, "clean_result", None) if main else None
    if not callable(fn):
        return {"available": False, "passed": [], "rejected": []}

    passed, rejected = [], []
    for row in rows:
        try:
            clean = fn(deepcopy(row), "sabina", query)
            if clean is None:
                rejected.append(_row_evidence(row))
            else:
                passed.append(_jsonable(clean))
        except Exception as exc:
            rejected.append({
                **_row_evidence(row),
                "error": f"{type(exc).__name__}: {exc}",
            })
    return {"available": True, "passed": passed, "rejected": rejected}


def _main_match(rows: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
    main = _load_main()
    matcher = getattr(main, "PRODUCT_MATCHER", None) if main else None
    fn = getattr(matcher, "match", None) if matcher else None
    if not callable(fn):
        return {"available": False, "passed": [], "rejected": []}

    passed, rejected = [], []
    for row in rows:
        try:
            result = fn(deepcopy(row), query)
            if result is None:
                rejected.append(_row_evidence(row))
            else:
                passed.append(_jsonable(result))
        except Exception as exc:
            rejected.append({
                **_row_evidence(row),
                "error": f"{type(exc).__name__}: {exc}",
            })
    return {"available": True, "passed": passed, "rejected": rejected}


def _main_dedupe(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    main = _load_main()
    fn = getattr(main, "dedupe_results", None) if main else None
    if not callable(fn):
        return {"available": False, "kept": rows, "dropped": []}

    try:
        # Use deep copies so we can compare stable serialized representations.
        source = deepcopy(rows)
        kept = fn(source)
        kept_json = {_stable(r) for r in kept}
        dropped = [r for r in source if _stable(r) not in kept_json]
        return {
            "available": True,
            "kept": _jsonable(kept),
            "dropped": _jsonable(dropped),
        }
    except Exception as exc:
        return {
            "available": True,
            "error": f"{type(exc).__name__}: {exc}",
            "kept": rows,
            "dropped": [],
        }


def _stable(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)


def _matrix(
    discovery_urls: List[str],
    extraction_by_url: List[Dict[str, Any]],
    direct_rows: List[Dict[str, Any]],
    stream_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    matrix = {}
    extracted = []
    for item in extraction_by_url:
        extracted.extend(
            r for r in item.get("rows", [])
            if isinstance(r, dict)
        )

    for expected in EXPECTED:
        def hits(rows):
            return [_row_evidence(r) for r in rows if _match_variant(r, expected)]

        discovery_hits = [
            u for u in discovery_urls
            if _match_variant({"url": u, "name": u}, expected)
        ]

        # URL/name discovery often uses a slug not identical to canonical name.
        # Also search extracted/direct/stream evidence against the URL itself.
        all_url_evidence = []
        for u in discovery_urls:
            if expected.lower().replace(" ", "-") in u.lower():
                all_url_evidence.append(u)

        ext_hits = hits(extracted)
        direct_hits = hits(direct_rows)
        stream_hits = hits(stream_rows)

        matrix[expected] = {
            "discovery": {
                "found": bool(discovery_hits or all_url_evidence or ext_hits or direct_hits),
                "candidate_urls": discovery_hits or all_url_evidence,
            },
            "extraction": {
                "success": bool(ext_hits),
                "rows": ext_hits,
            },
            "direct_search": {
                "found": bool(direct_hits),
                "rows": direct_hits,
            },
            "stream_search": {
                "found": bool(stream_hits),
                "rows": stream_hits,
            },
        }
    return matrix


@router.get("/diagnose-sabina-born-in-roma-v2")
def diagnose_sabina_born_in_roma_v2(
    q: str = Query("Born in Roma", min_length=1, max_length=120)
):
    started = time.monotonic()

    # 1. Discovery — hard kill.
    discovery = _run_hard("discovery", q, DISCOVERY_TIMEOUT)
    urls = discovery.get("value", []) if discovery.get("ok") else []
    urls = [str(u) for u in urls if u]

    # Keep discovery diagnostic bounded. We do not launch hundreds of requests.
    urls = list(dict.fromkeys(urls))[:40]

    # 2. Extraction — each URL independently hard-timed.
    extraction = []
    for url in urls:
        if time.monotonic() - started >= GLOBAL_TIMEOUT:
            extraction.append({
                "url": url,
                "status": "NOT_RUN_GLOBAL_DEADLINE",
                "rows": [],
            })
            continue

        result = _run_hard("extract", q, EXTRACTION_TIMEOUT, url=url)
        extraction.append({
            "url": url,
            "status": (
                "SUCCESS" if result.get("ok") and result.get("value")
                else "FAILED_TIMEOUT" if result.get("timeout")
                else "FAILED_EXCEPTION" if not result.get("ok")
                else "FAILED_EMPTY"
            ),
            "elapsed": result.get("elapsed"),
            "error": result.get("error"),
            "rows": result.get("value", []) if result.get("ok") else [],
        })

    # 3. Direct search and 4. stream search.
    direct = _run_hard("search", q, SEARCH_TIMEOUT)
    stream = _run_hard("stream", q, STREAM_TIMEOUT)

    direct_rows = direct.get("value", []) if direct.get("ok") else []
    stream_rows = stream.get("value", []) if stream.get("ok") else []

    # 5. Downstream observation only.
    # Do not alter the production pipeline; apply current functions to copies.
    clean = _main_clean(stream_rows, q)
    matching = _main_match(stream_rows, q)
    dedup = _main_dedupe(stream_rows)

    matrix = _matrix(urls, extraction, direct_rows, stream_rows)

    found_direct = [v for v in EXPECTED if matrix[v]["direct_search"]["found"]]
    found_stream = [v for v in EXPECTED if matrix[v]["stream_search"]["found"]]
    found_extraction = [v for v in EXPECTED if matrix[v]["extraction"]["success"]]

    missing_stream = [v for v in EXPECTED if v not in found_stream]
    missing_direct = [v for v in EXPECTED if v not in found_direct]

    if len(missing_stream) == 4:
        headline = "STREAM_MISSING_4"
    elif not missing_stream:
        headline = "STREAM_HAS_ALL_18"
    else:
        headline = f"STREAM_MISSING_{len(missing_stream)}"

    return {
        "ok": True,
        "diagnostic_version": "2-hard-timeout",
        "architecture": "forensic; no production mutation",
        "query": q,
        "elapsed": round(time.monotonic() - started, 3),
        "deadline_seconds": GLOBAL_TIMEOUT,
        "headline": headline,
        "expected_count": len(EXPECTED),
        "expected": EXPECTED,
        "summary": {
            "discovery_url_count": len(urls),
            "extraction_success_count": sum(
                1 for x in extraction if x["status"] == "SUCCESS"
            ),
            "direct_search_count": len(direct_rows),
            "stream_search_count": len(stream_rows),
            "missing_direct": missing_direct,
            "missing_stream": missing_stream,
            "missing_extraction": [
                v for v in EXPECTED if v not in found_extraction
            ],
        },
        "loss_point_matrix": matrix,
        "discovery": {
            "status": "SUCCESS" if discovery.get("ok") else (
                "TIMEOUT" if discovery.get("timeout") else "FAILED"
            ),
            "elapsed": discovery.get("elapsed"),
            "url_count": len(urls),
            "urls": urls,
            "error": discovery.get("error"),
        },
        "extraction": extraction,
        "direct_search": {
            "status": "SUCCESS" if direct.get("ok") else (
                "TIMEOUT" if direct.get("timeout") else "FAILED"
            ),
            "elapsed": direct.get("elapsed"),
            "count": len(direct_rows),
            "rows": [_row_evidence(r) for r in direct_rows if isinstance(r, dict)],
            "error": direct.get("error"),
        },
        "stream_search": {
            "status": "SUCCESS" if stream.get("ok") else (
                "TIMEOUT" if stream.get("timeout") else "FAILED"
            ),
            "elapsed": stream.get("elapsed"),
            "count": len(stream_rows),
            "rows": [_row_evidence(r) for r in stream_rows if isinstance(r, dict)],
            "error": stream.get("error"),
        },
        "downstream_observation": {
            "clean_result": {
                "available": clean.get("available"),
                "input_count": len(stream_rows),
                "passed_count": len(clean.get("passed", [])),
                "rejected_count": len(clean.get("rejected", [])),
                "rejected": clean.get("rejected", []),
            },
            "product_matcher": {
                "available": matching.get("available"),
                "input_count": len(stream_rows),
                "passed_count": len(matching.get("passed", [])),
                "rejected_count": len(matching.get("rejected", [])),
                "rejected": matching.get("rejected", []),
            },
            "dedupe": {
                "available": dedup.get("available"),
                "input_count": len(stream_rows),
                "kept_count": len(dedup.get("kept", [])),
                "dropped_count": len(dedup.get("dropped", [])),
                "dropped": [
                    _row_evidence(r)
                    for r in dedup.get("dropped", [])
                    if isinstance(r, dict)
                ],
                "error": dedup.get("error"),
            },
        },
        "interpretation": {
            "rule": (
                "A variant is considered discovered when its canonical evidence "
                "appears in discovered URLs or later extracted/direct evidence. "
                "Extraction is successful when at least one extracted row matches. "
                "Downstream sections are observational and never modify production data."
            ),
            "next_step": (
                "If a missing variant appears in direct_search but not stream_search, "
                "the loss is in the streaming path. If it appears in extraction but "
                "not direct/stream, inspect search/validation. If it appears in stream "
                "but is absent after clean/matching/dedupe, the loss is downstream."
            ),
        },
    }
