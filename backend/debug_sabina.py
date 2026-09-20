from __future__ import annotations

"""
ScentHunter - Sabina Born in Roma forensic diagnostic.

PURPOSE
-------
Observe the REAL Sabina search_stream() path in the same FastAPI process.

This file is diagnostic-only:
- it does NOT modify scrapers/sabina/scraper.py on disk;
- it does NOT modify product_matcher.py;
- it does NOT modify family_registry.json;
- it does NOT call Sabina search() a second time;
- it temporarily wraps the exact discovery/extraction functions used by
  the existing Sabina stream adapter installed by sitecustomize.py.

ENDPOINT
--------
GET /diagnose-sabina?q=Born%20in%20Roma

IMPORTANT
---------
Do not replace the production Sabina scraper. This file only observes it.
"""

import copy
import importlib
import re
import time
from typing import Any

from fastapi import APIRouter, Query

router = APIRouter()

# CURRENT FAMILY REGISTRY: 20 Born in Roma identities.
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
    "Born in Roma Donna Pink PP",
    "Born in Roma Uomo Rockstud Noir",
]


def norm(value: Any) -> str:
    value = str(value or "").casefold()
    value = re.sub(r"[^a-z0-9à-ÿäöüß]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def evidence(row: Any) -> dict:
    if not isinstance(row, dict):
        return {"value": repr(row)}

    source = row.get("source")
    if not isinstance(source, dict):
        source = {}

    return {
        "name": row.get("name"),
        "title": row.get("title"),
        "canonical_name": row.get("canonical_name"),
        "catalog_variant": row.get("catalog_variant"),
        "brand": row.get("brand") or row.get("source_brand"),
        "source_name": source.get("source_name"),
        "url": row.get("url") or source.get("url"),
        "size_ml": row.get("size_ml"),
        "price": row.get("price"),
        "availability": row.get("availability"),
        "store_product_id": row.get("store_product_id"),
        "product_id": row.get("product_id"),
        "sku": row.get("sku"),
        "family_id": row.get("family_id"),
        "match_method": row.get("match_method"),
        "match_score": row.get("match_score"),
    }


def row_text(row: Any) -> str:
    if not isinstance(row, dict):
        return ""

    values = []
    for key in (
        "name", "title", "product_name", "canonical_name",
        "catalog_variant", "brand", "source_brand",
        "product_line", "variant", "url",
    ):
        value = row.get(key)
        if value not in (None, ""):
            values.append(str(value))

    source = row.get("source")
    if isinstance(source, dict):
        for key in (
            "name", "title", "product_name", "source_name",
            "brand", "source_brand", "url",
        ):
            value = source.get(key)
            if value not in (None, ""):
                values.append(str(value))

    return norm(" ".join(values))


def exact_variant_match(row: Any, expected: str) -> bool:
    """Broad diagnostic identity check; it does not change production matching."""
    target = norm(expected)
    if not target:
        return False

    explicit = []
    if isinstance(row, dict):
        for key in (
            "name", "title", "product_name",
            "canonical_name", "catalog_variant",
        ):
            if row.get(key):
                explicit.append(norm(row[key]))

        source = row.get("source")
        if isinstance(source, dict):
            for key in ("name", "title", "product_name", "source_name"):
                if source.get(key):
                    explicit.append(norm(source[key]))

    if target in explicit:
        return True

    text = row_text(row)
    return f" {target} " in f" {text} "


def classify_observed_rows(rows: list[dict]) -> dict[str, list[dict]]:
    return {
        expected: [
            evidence(row)
            for row in rows
            if exact_variant_match(row, expected)
        ]
        for expected in EXPECTED
    }


def safe_copy(value: Any) -> Any:
    try:
        return copy.deepcopy(value)
    except Exception:
        return repr(value)


def call_optional_clean_result(main, row: dict, query: str) -> tuple[str, Any]:
    clean = getattr(main, "clean_result", None)
    if not callable(clean):
        return "UNAVAILABLE", None

    attempts = [
        lambda: clean(copy.deepcopy(row), "sabina", query),
        lambda: clean(copy.deepcopy(row), query),
    ]

    last_error = None
    for attempt in attempts:
        try:
            result = attempt()
            return ("PASSED" if result is not None else "REJECTED"), result
        except TypeError as exc:
            last_error = exc
            continue
        except Exception as exc:
            return "ERROR", f"{type(exc).__name__}: {exc}"

    return "ERROR", f"{type(last_error).__name__}: {last_error}"


def call_optional_matcher(main, row: dict, query: str) -> tuple[str, Any]:
    candidates = []
    for attr in ("PRODUCT_MATCHER", "product_matcher", "MATCHER"):
        obj = getattr(main, attr, None)
        if obj is not None:
            candidates.append(obj)

    for obj in candidates:
        fn = getattr(obj, "match", None)
        if not callable(fn):
            continue

        try:
            result = fn(copy.deepcopy(row), query)
            return ("PASSED" if result is not None else "REJECTED"), result
        except TypeError:
            try:
                result = fn(copy.deepcopy(row), query, "sabina")
                return ("PASSED" if result is not None else "REJECTED"), result
            except Exception as exc:
                return "ERROR", f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            return "ERROR", f"{type(exc).__name__}: {exc}"

    return "UNAVAILABLE", None


def observe_dedupe(main, rows: list[dict]) -> dict:
    fn = getattr(main, "dedupe_results", None)
    if not callable(fn):
        return {"available": False, "kept": [], "dropped": []}

    source = copy.deepcopy(rows)

    try:
        kept = fn(copy.deepcopy(source))
    except Exception as exc:
        return {
            "available": True,
            "error": f"{type(exc).__name__}: {exc}",
            "kept": [],
            "dropped": [],
        }

    import json

    kept_keys = {
        json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        for item in kept
        if isinstance(item, dict)
    }

    dropped = [
        evidence(item)
        for item in source
        if isinstance(item, dict)
        and json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        not in kept_keys
    ]

    return {
        "available": True,
        "kept": [safe_copy(x) for x in kept if isinstance(x, dict)],
        "dropped": dropped,
    }


def url_might_identify(url: str, expected: str) -> bool:
    """Discovery hint only: all identity words must occur in the URL."""
    u = norm(url)
    parts = [p for p in norm(expected).split() if p]
    return bool(parts) and all(part in u for part in parts)


@router.get("/diagnose-sabina-born-in-roma")
def diagnose_sabina_born_in_roma(
    q: str = Query("Born in Roma", min_length=1, max_length=120),
):
    started = time.monotonic()

    sabina = importlib.import_module("scrapers.sabina.scraper")
    main = importlib.import_module("main")

    stream = getattr(sabina, "search_stream", None)
    original_discover = getattr(sabina, "_discover_from_first_party", None)
    original_extract = getattr(sabina, "_extract_product_page", None)

    if not callable(stream):
        return {
            "ok": False,
            "error": "LIVE_SEARCH_STREAM_NOT_AVAILABLE",
            "hint": "sitecustomize.py did not install Sabina search_stream()",
        }

    if not callable(original_discover):
        return {"ok": False, "error": "DISCOVERY_FUNCTION_NOT_AVAILABLE"}

    if not callable(original_extract):
        return {"ok": False, "error": "EXTRACTION_FUNCTION_NOT_AVAILABLE"}

    trace = {
        "discovery": {
            "called": False,
            "elapsed_seconds": None,
            "urls": [],
            "error": None,
        },
        "extraction": [],
        "stream_emissions": [],
    }

    def traced_discover(session, query):
        trace["discovery"]["called"] = True
        t0 = time.monotonic()
        try:
            result = original_discover(session, query)
            urls = list(result or [])
            trace["discovery"]["elapsed_seconds"] = round(time.monotonic() - t0, 3)
            trace["discovery"]["urls"] = urls
            return urls
        except Exception as exc:
            trace["discovery"]["elapsed_seconds"] = round(time.monotonic() - t0, 3)
            trace["discovery"]["error"] = f"{type(exc).__name__}: {exc}"
            raise

    def traced_extract(url, query):
        t0 = time.monotonic()
        item = {
            "url": url,
            "elapsed_seconds": None,
            "status": None,
            "rows": [],
            "error": None,
        }

        try:
            result = original_extract(url, query)
            rows = list(result or [])
            item["elapsed_seconds"] = round(time.monotonic() - t0, 3)
            item["rows"] = [
                evidence(row) for row in rows if isinstance(row, dict)
            ]
            item["status"] = "SUCCESS" if item["rows"] else "EMPTY"
            return rows
        except Exception as exc:
            item["elapsed_seconds"] = round(time.monotonic() - t0, 3)
            item["status"] = "EXCEPTION"
            item["error"] = f"{type(exc).__name__}: {exc}"
            return []
        finally:
            trace["extraction"].append(item)

    setattr(sabina, "_discover_from_first_party", traced_discover)
    setattr(sabina, "_extract_product_page", traced_extract)

    emitted: list[dict] = []
    stream_error = None
    stream_started = time.monotonic()

    def emit(row):
        if not isinstance(row, dict):
            return
        item = copy.deepcopy(row)
        emitted.append(item)
        trace["stream_emissions"].append(evidence(item))

    try:
        # Exactly one live Sabina search_stream execution.
        stream(q, emit)
    except Exception as exc:
        stream_error = f"{type(exc).__name__}: {exc}"
    finally:
        setattr(sabina, "_discover_from_first_party", original_discover)
        setattr(sabina, "_extract_product_page", original_extract)

    stream_elapsed = round(time.monotonic() - stream_started, 3)
    stream_by_variant = classify_observed_rows(emitted)

    extraction_by_variant = {}
    for expected in EXPECTED:
        hits = []
        for item in trace["extraction"]:
            for row in item["rows"]:
                if exact_variant_match(row, expected):
                    hits.append({
                        "url": item["url"],
                        "status": item["status"],
                        "elapsed_seconds": item["elapsed_seconds"],
                        "row": row,
                        "error": item["error"],
                    })
        extraction_by_variant[expected] = hits

    discovery_by_variant = {}
    for expected in EXPECTED:
        hits = [
            url
            for url in trace["discovery"]["urls"]
            if url_might_identify(url, expected)
        ]
        discovery_by_variant[expected] = {
            "url_evidence": bool(hits),
            "candidate_urls": hits,
        }

    downstream = []
    for row in emitted:
        clean_status, clean_result = call_optional_clean_result(main, row, q)
        matcher_status, matcher_result = call_optional_matcher(main, row, q)
        downstream.append({
            "input": evidence(row),
            "clean_result": {
                "status": clean_status,
                "output": safe_copy(clean_result)
                if clean_status == "PASSED"
                else clean_result,
            },
            "product_matcher": {
                "status": matcher_status,
                "output": safe_copy(matcher_result)
                if matcher_status == "PASSED"
                else matcher_result,
            },
        })

    clean_passed = [
        item["input"]
        for item in downstream
        if item["clean_result"]["status"] == "PASSED"
    ]
    matcher_passed = [
        item["input"]
        for item in downstream
        if item["product_matcher"]["status"] == "PASSED"
    ]

    dedupe = observe_dedupe(main, emitted)
    matrix = {}
    loss = {}

    for expected in EXPECTED:
        discovery = discovery_by_variant[expected]
        extraction = extraction_by_variant[expected]
        stream_rows = stream_by_variant[expected]

        clean_rows = [
            item["input"]
            for item in downstream
            if item["clean_result"]["status"] == "PASSED"
            and exact_variant_match(item["input"], expected)
        ]

        matcher_rows = [
            item["input"]
            for item in downstream
            if item["product_matcher"]["status"] == "PASSED"
            and exact_variant_match(item["input"], expected)
        ]

        dedup_kept = [
            item
            for item in dedupe.get("kept", [])
            if exact_variant_match(item, expected)
        ]

        matrix[expected] = {
            "discovery": discovery,
            "extraction": {
                "found": bool(extraction),
                "candidates": extraction,
            },
            "stream": {
                "found": bool(stream_rows),
                "rows": stream_rows,
            },
            "clean_result": {
                "found": bool(clean_rows),
                "rows": clean_rows,
            },
            "product_matcher": {
                "found": bool(matcher_rows),
                "rows": matcher_rows,
            },
            "dedupe": {
                "found": bool(dedup_kept),
                "rows": dedup_kept,
            },
        }

        if not extraction and not discovery["url_evidence"]:
            loss[expected] = "NOT_DISCOVERED_EVIDENCE"
        elif not extraction:
            loss[expected] = "DISCOVERED_URL_BUT_EXTRACTION_FAILED"
        elif not stream_rows:
            loss[expected] = "EXTRACTED_BUT_NOT_EMITTED"
        elif not clean_rows:
            loss[expected] = "STREAM_EMITTED_BUT_CLEAN_RESULT_REJECTED"
        elif not matcher_rows:
            loss[expected] = "CLEANED_BUT_PRODUCT_MATCHER_REJECTED"
        elif not dedup_kept:
            loss[expected] = "MATCHED_BUT_DEDUPE_DROPPED"
        else:
            loss[expected] = "SURVIVED_OBSERVED_STAGES"

    counts = {
        "expected_variants": len(EXPECTED),
        "discovery_url_count": len(trace["discovery"]["urls"]),
        "extraction_url_count": len(trace["extraction"]),
        "stream_emission_count": len(emitted),
        "stream_variant_count": sum(
            1 for expected in EXPECTED if matrix[expected]["stream"]["found"]
        ),
        "clean_result_variant_count": sum(
            1 for expected in EXPECTED if matrix[expected]["clean_result"]["found"]
        ),
        "product_matcher_variant_count": sum(
            1 for expected in EXPECTED if matrix[expected]["product_matcher"]["found"]
        ),
        "dedupe_variant_count": sum(
            1 for expected in EXPECTED if matrix[expected]["dedupe"]["found"]
        ),
    }

    return {
        "ok": True,
        "diagnostic_version": "5-born-in-roma-20-real-stream-one-run",
        "query": q,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "stream": {
            "module": getattr(stream, "__module__", None),
            "function": getattr(stream, "__name__", None),
            "elapsed_seconds": stream_elapsed,
            "error": stream_error,
        },
        "counts": counts,
        "headline": (
            "ALL_20_SURVIVED"
            if counts["dedupe_variant_count"] == 20
            else "VARIANTS_MISSING"
        ),
        "loss_by_variant": loss,
        "matrix": matrix,
        "raw_trace": trace,
        "downstream_observation": {
            "clean_result_available": any(
                item["clean_result"]["status"] != "UNAVAILABLE"
                for item in downstream
            ),
            "product_matcher_available": any(
                item["product_matcher"]["status"] != "UNAVAILABLE"
                for item in downstream
            ),
            "emissions": downstream,
            "clean_passed_count": len(clean_passed),
            "matcher_passed_count": len(matcher_passed),
            "dedupe": dedupe,
        },
        "direct_search": {
            "executed": False,
            "reason": (
                "This diagnostic intentionally executes only the live "
                "search_stream path."
            ),
        },
    }
