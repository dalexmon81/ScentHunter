from __future__ import annotations

"""
ScentHunter — Sabina Born in Roma forensic diagnostic v3.

This diagnostic deliberately runs INSIDE the same Python process as the
FastAPI application. It does not create a second scraper implementation and
does not use multiprocessing.

It observes the REAL Sabina search_stream path by temporarily wrapping:
  - _discover_from_first_party
  - _extract_product_page

The wrappers only record inputs/outputs/errors and immediately delegate to the
real functions. ProductMatcher, family_registry and the production scraper
are never modified on disk.

Endpoint:
  GET /diagnose-sabina-born-in-roma-v3?q=Born%20in%20Roma

This module must be included by the existing debug router or imported by
main.py before the endpoint can be reached.
"""

import importlib
import json
import re
import time
from copy import deepcopy
from typing import Any

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

GLOBAL_DEADLINE_SECONDS = 65


def _norm(v: Any) -> str:
    s = str(v or "").casefold().strip()
    s = re.sub(r"[^a-z0-9à-ÿäöüß]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _safe(v: Any) -> Any:
    try:
        return json.loads(json.dumps(v, ensure_ascii=False, default=str))
    except Exception:
        return str(v)


def _evidence(row: Any) -> dict:
    if not isinstance(row, dict):
        return {"value": _safe(row)}

    source = row.get("source")
    if not isinstance(source, dict):
        source = {}

    return {
        "name": row.get("name"),
        "canonical_name": row.get("canonical_name"),
        "catalog_variant": row.get("catalog_variant"),
        "source_name": source.get("source_name"),
        "brand": row.get("brand") or source.get("source_brand"),
        "url": row.get("url") or source.get("url"),
        "size_ml": row.get("size_ml"),
        "price_num": row.get("price_num"),
        "availability": row.get("availability"),
        "store_product_id": row.get("store_product_id"),
        "sku": row.get("sku"),
        "match_method": row.get("match_method"),
        "match_score": row.get("match_score"),
    }


def _names(row: Any) -> list[str]:
    if not isinstance(row, dict):
        return []

    out = []
    for key in ("name", "title", "canonical_name", "catalog_variant"):
        if row.get(key):
            out.append(str(row[key]))

    source = row.get("source")
    if isinstance(source, dict) and source.get("source_name"):
        out.append(str(source["source_name"]))

    return out


def _matches(row: Any, expected: str) -> bool:
    target = _norm(expected)
    vals = [_norm(x) for x in _names(row) if x]

    if target in vals:
        return True

    target_tokens = set(target.split())
    for val in vals:
        tokens = set(val.split())
        if target_tokens and len(tokens & target_tokens) / len(target_tokens) >= 0.80:
            return True

    return False


def _variant_rows(rows: list[dict]) -> dict[str, list[dict]]:
    return {
        expected: [
            _evidence(row)
            for row in rows
            if _matches(row, expected)
        ]
        for expected in EXPECTED
    }


def _url_hint(url: str, expected: str) -> bool:
    """
    Diagnostic-only URL heuristic. It catches common Sabina slug ordering
    without pretending this is the scraper's matching algorithm.
    """
    u = _norm(url).replace(" ", "-")
    t = _norm(expected).replace(" ", "-")
    if t in u:
        return True

    # Uomo Ivory -> ivory-uomo and similar reordered slugs.
    parts = [p for p in t.split("-") if p]
    return len(parts) >= 3 and all(p in u for p in parts)


def _downstream(main, rows: list[dict], query: str) -> dict:
    result = {
        "clean_result": {
            "available": False,
            "passed": [],
            "rejected": [],
        },
        "product_matcher": {
            "available": False,
            "passed": [],
            "rejected": [],
        },
        "dedupe": {
            "available": False,
            "kept": [],
            "dropped": [],
        },
    }

    clean = getattr(main, "clean_result", None)
    if callable(clean):
        result["clean_result"]["available"] = True
        for row in rows:
            try:
                x = clean(deepcopy(row), "sabina", query)
                if x is None:
                    result["clean_result"]["rejected"].append(_evidence(row))
                else:
                    result["clean_result"]["passed"].append(_safe(x))
            except Exception as exc:
                result["clean_result"]["rejected"].append({
                    **_evidence(row),
                    "error": f"{type(exc).__name__}: {exc}",
                })

    matcher = getattr(main, "PRODUCT_MATCHER", None)
    match = getattr(matcher, "match", None) if matcher else None
    if callable(match):
        result["product_matcher"]["available"] = True
        for row in rows:
            try:
                x = match(deepcopy(row), query)
                if x is None:
                    result["product_matcher"]["rejected"].append(_evidence(row))
                else:
                    result["product_matcher"]["passed"].append(_safe(x))
            except Exception as exc:
                result["product_matcher"]["rejected"].append({
                    **_evidence(row),
                    "error": f"{type(exc).__name__}: {exc}",
                })

    dedupe = getattr(main, "dedupe_results", None)
    if callable(dedupe):
        result["dedupe"]["available"] = True
        source = deepcopy(rows)
        try:
            kept = dedupe(source)
            # Compare serialized row values, not object identity.
            kept_keys = {
                json.dumps(x, ensure_ascii=False, sort_keys=True, default=str)
                for x in kept
            }
            dropped = [
                x for x in source
                if json.dumps(x, ensure_ascii=False, sort_keys=True, default=str)
                not in kept_keys
            ]
            result["dedupe"]["kept"] = _safe(kept)
            result["dedupe"]["dropped"] = [
                _evidence(x) for x in dropped
            ]
        except Exception as exc:
            result["dedupe"]["error"] = f"{type(exc).__name__}: {exc}"

    return result


@router.get("/diagnose-sabina-born-in-roma-v3")
def diagnose_sabina_born_in_roma_v3(
    q: str = Query("Born in Roma", min_length=1, max_length=120)
):
    started = time.monotonic()
    sabina = importlib.import_module("scrapers.sabina.scraper")
    main = importlib.import_module("main")

    # We observe the exact functions used by the live Sabina stream adapter.
    original_discover = getattr(sabina, "_discover_from_first_party", None)
    original_extract = getattr(sabina, "_extract_product_page", None)
    stream = getattr(sabina, "search_stream", None)

    if not callable(original_discover):
        return {
            "ok": False,
            "error": "_discover_from_first_party is not available",
        }

    if not callable(original_extract):
        return {
            "ok": False,
            "error": "_extract_product_page is not available",
        }

    if not callable(stream):
        return {
            "ok": False,
            "error": "search_stream is not available in the live runtime",
        }

    trace = {
        "discovery": {
            "called": False,
            "elapsed": None,
            "urls": [],
            "error": None,
        },
        "extraction": [],
        "stream_emissions": [],
    }

    def traced_discover(session, query):
        trace["discovery"]["called"] = True
        t = time.monotonic()
        try:
            urls = original_discover(session, query)
            urls = list(urls or [])
            trace["discovery"]["elapsed"] = round(time.monotonic() - t, 3)
            trace["discovery"]["urls"] = urls
            return urls
        except Exception as exc:
            trace["discovery"]["elapsed"] = round(time.monotonic() - t, 3)
            trace["discovery"]["error"] = (
                f"{type(exc).__name__}: {exc}"
            )
            raise

    def traced_extract(url, query):
        t = time.monotonic()
        item = {
            "url": url,
            "elapsed": None,
            "status": None,
            "rows": [],
            "error": None,
        }
        try:
            rows = original_extract(url, query)
            rows = [] if rows is None else list(rows)
            item["elapsed"] = round(time.monotonic() - t, 3)
            item["rows"] = [_evidence(x) for x in rows if isinstance(x, dict)]
            item["status"] = "SUCCESS" if item["rows"] else "EMPTY"
            return rows
        except Exception as exc:
            item["elapsed"] = round(time.monotonic() - t, 3)
            item["status"] = "EXCEPTION"
            item["error"] = f"{type(exc).__name__}: {exc}"
            return []
        finally:
            trace["extraction"].append(item)

    # Temporarily replace references used by the existing stream closure.
    # Always restore them before returning.
    setattr(sabina, "_discover_from_first_party", traced_discover)
    setattr(sabina, "_extract_product_page", traced_extract)

    emitted: list[dict] = []

    def emit(row):
        if isinstance(row, dict):
            item = deepcopy(row)
            emitted.append(item)
            trace["stream_emissions"].append(_evidence(item))

    stream_error = None
    stream_started = time.monotonic()

    try:
        # This is the REAL existing stream function, not a reimplementation.
        stream(q, emit)
    except Exception as exc:
        stream_error = f"{type(exc).__name__}: {exc}"
    finally:
        setattr(sabina, "_discover_from_first_party", original_discover)
        setattr(sabina, "_extract_product_page", original_extract)

    stream_elapsed = round(time.monotonic() - stream_started, 3)

    extracted_rows = []
    for item in trace["extraction"]:
        # Extraction trace stores only evidence; use emitted rows for the
        # authoritative stream-stage data.
        pass

    stream_variants = _variant_rows(emitted)
    discovered_urls = trace["discovery"]["urls"]

    # Direct search is intentionally NOT executed. That was the mistake in
    # the previous diagnostic: it doubled the work and obscured the real
    # streaming path.
    direct = {
        "executed": False,
        "reason": "Not executed: diagnostic observes the real stream path only.",
    }

    downstream = _downstream(main, emitted, q)

    clean_rows = downstream["clean_result"]["passed"]
    match_rows = downstream["product_matcher"]["passed"]
    dedup_rows = downstream["dedupe"]["kept"]

    matrix = {}
    for expected in EXPECTED:
        discovery_url_hits = [
            u for u in discovered_urls
            if _url_hint(u, expected)
        ]
        extraction_hits = [
            x for x in trace["extraction"]
            if any(
                _matches(r, expected)
                for r in x.get("rows", [])
            )
        ]
        stream_hits = stream_variants[expected]

        clean_hits = [
            r for r in clean_rows
            if isinstance(r, dict) and _matches(r, expected)
        ]
        match_hits = [
            r for r in match_rows
            if isinstance(r, dict) and _matches(r, expected)
        ]
        dedup_hits = [
            r for r in dedup_rows
            if isinstance(r, dict) and _matches(r, expected)
        ]

        matrix[expected] = {
            "discovery": {
                "found": bool(discovery_url_hits),
                "candidate_urls": discovery_url_hits,
            },
            "extraction": {
                "found": bool(extraction_hits),
                "candidates": extraction_hits,
            },
            "stream": {
                "found": bool(stream_hits),
                "rows": stream_hits,
            },
            "validation": {
                "found": bool(clean_hits),
                "rows": [_safe(x) for x in clean_hits],
            },
            "matching": {
                "found": bool(match_hits),
                "rows": [_safe(x) for x in match_hits],
            },
            "dedup": {
                "found": bool(dedup_hits),
                "rows": [_safe(x) for x in dedup_hits],
            },
        }

    found_stream = [
        x for x in EXPECTED
        if matrix[x]["stream"]["found"]
    ]
    missing_stream = [
        x for x in EXPECTED
        if x not in found_stream
    ]

    # Determine a loss label from actual observed stages.
    loss = {}
    for expected in EXPECTED:
        m = matrix[expected]
        if not m["discovery"]["found"]:
            loss[expected] = "NOT_DISCOVERED_BY_FIRST_PARTY"
        elif not m["extraction"]["found"]:
            loss[expected] = "DISCOVERED_BUT_EXTRACTION_FAILED"
        elif not m["stream"]["found"]:
            loss[expected] = "EXTRACTED_BUT_NOT_EMITTED_BY_STREAM"
        elif not m["validation"]["found"]:
            loss[expected] = "STREAM_EMITTED_BUT_CLEAN_RESULT_REJECTED"
        elif not m["matching"]["found"]:
            loss[expected] = "CLEANED_BUT_PRODUCT_MATCHER_REJECTED"
        elif not m["dedup"]["found"]:
            loss[expected] = "MATCHED_BUT_DEDUP_DROPPED"
        else:
            loss[expected] = "SURVIVED_ALL_OBSERVED_STAGES"

    return {
        "ok": True,
        "diagnostic_version": "3-live-path-single-run",
        "architecture": "forensic; same-process observation; no production mutation",
        "query": q,
        "elapsed": round(time.monotonic() - started, 3),
        "global_deadline_note": (
            f"This endpoint performs one live stream run only. "
            f"Observed runtime was {stream_elapsed}s. "
            f"No second direct search is executed."
        ),
        "expected_count": len(EXPECTED),
        "expected": EXPECTED,
        "headline": (
            "STREAM_HAS_ALL_18"
            if not missing_stream
            else f"STREAM_MISSING_{len(missing_stream)}"
        ),
        "summary": {
            "discovery_url_count": len(discovered_urls),
            "extraction_attempt_count": len(trace["extraction"]),
            "stream_emission_count": len(emitted),
            "stream_found_count": len(found_stream),
            "missing_stream": missing_stream,
            "loss_by_variant": loss,
        },
        "live_path": {
            "stream_called": True,
            "stream_elapsed": stream_elapsed,
            "stream_error": stream_error,
        },
        "direct_search": direct,
        "discovery": trace["discovery"],
        "extraction": trace["extraction"],
        "stream_emissions": trace["stream_emissions"],
        "loss_point_matrix": matrix,
        "downstream_observation": downstream,
    }
