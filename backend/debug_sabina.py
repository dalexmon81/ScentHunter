from __future__ import annotations

"""
ScentHunter - Sabina Born in Roma forensic diagnostic

Standalone diagnostic module.
DO NOT import/modify ProductMatcher, family_registry, or Sabina production code.
It only observes the current implementation and reports where each expected
Born in Roma variant disappears.

To use:
  1. Copy this file to backend/debug_sabina_born_in_roma.py
  2. Temporarily register it manually in main.py if desired, using:
       from debug_sabina_born_in_roma import router
       app.include_router(router)
  3. Query:
       GET /diagnose-sabina-born-in-roma?q=Born%20in%20Roma

No production scraper code is changed by this file.
"""

import importlib
import json
import re
import time
import traceback
from collections import defaultdict
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Query

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None


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

EXPECTED_BY_NORM = {}


def _norm(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = re.sub(r"[^a-z0-9à-ÿ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _safe_json(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, default=str)
        return value
    except Exception:
        return str(value)


def _safe_call(fn, *args, **kwargs):
    try:
        return {
            "ok": True,
            "value": fn(*args, **kwargs),
            "error": None,
            "traceback": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "value": None,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def _flatten_text(row: Dict[str, Any]) -> str:
    source = row.get("source") if isinstance(row.get("source"), dict) else {}
    identity = row.get("identity") if isinstance(row.get("identity"), dict) else {}
    attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}

    values = [
        row.get("name"),
        row.get("title"),
        row.get("canonical_name"),
        row.get("catalog_variant"),
        row.get("brand"),
        row.get("url"),
        source.get("source_name"),
        source.get("source_brand"),
    ]

    for value in attrs.values():
        if isinstance(value, dict):
            values.append(value.get("value"))
        else:
            values.append(value)

    for value in identity.values():
        if isinstance(value, dict):
            values.append(value.get("value"))
        else:
            values.append(value)

    return " ".join(str(v or "") for v in values)


def _candidate_matches_variant(row: Dict[str, Any], expected: str) -> Dict[str, Any]:
    source_name = ""
    source = row.get("source")
    if isinstance(source, dict):
        source_name = str(source.get("source_name") or "")

    names = [
        str(row.get("name") or ""),
        str(row.get("title") or ""),
        str(row.get("canonical_name") or ""),
        str(row.get("catalog_variant") or ""),
        source_name,
    ]

    target = _norm(expected)
    exact = any(_norm(name) == target for name in names if name)

    # More permissive evidence for pre-matcher raw names, e.g.
    # "Born In Roma Ivory Uomo" versus canonical "Born in Roma Uomo Ivory".
    target_tokens = set(target.split())
    strongest_name = ""
    strongest_score = 0.0

    for name in names:
        tokens = set(_norm(name).split())
        if not tokens or not target_tokens:
            continue
        overlap = len(tokens & target_tokens) / max(1, len(target_tokens))
        if overlap > strongest_score:
            strongest_score = overlap
            strongest_name = name

    return {
        "exact": exact,
        "token_overlap": round(strongest_score, 3),
        "best_name": strongest_name,
        "target": expected,
    }


def _classify_raw_variant(row: Dict[str, Any]) -> List[str]:
    """
    Produce likely canonical family variant matches without mutating anything.
    This is intentionally only a diagnostic heuristic; official matching is
    still delegated to the current ProductMatcher below.
    """
    evidence = []
    names = []

    source = row.get("source")
    if isinstance(source, dict):
        names.append(str(source.get("source_name") or ""))

    names.extend(
        str(row.get(key) or "")
        for key in ("name", "title", "canonical_name", "catalog_variant")
    )

    normalized_names = [_norm(n) for n in names if n]

    for expected in EXPECTED:
        target = _norm(expected)
        if target in normalized_names:
            evidence.append(expected)
            continue

        target_tokens = set(target.split())
        best = max(
            (
                len(set(name.split()) & target_tokens) / max(1, len(target_tokens))
                for name in normalized_names
            ),
            default=0.0,
        )
        if best >= 0.80:
            evidence.append(expected)

    return evidence


def _extract_raw_stream(sabina, query: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "search_stream_exists": callable(getattr(sabina, "search_stream", None)),
        "rows": [],
        "errors": [],
    }

    stream = getattr(sabina, "search_stream", None)
    if not callable(stream):
        return out

    emitted: List[Dict[str, Any]] = []

    def emit(row):
        if isinstance(row, dict):
            emitted.append(deepcopy(row))

    started = time.monotonic()

    try:
        returned = stream(query, emit)

        if returned is not None:
            try:
                for row in returned:
                    if isinstance(row, dict):
                        emitted.append(deepcopy(row))
            except TypeError:
                pass

        out["elapsed"] = round(time.monotonic() - started, 3)
        out["rows"] = emitted
        out["count"] = len(emitted)
    except Exception as exc:
        out["elapsed"] = round(time.monotonic() - started, 3)
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["traceback"] = traceback.format_exc()
        out["rows"] = emitted
        out["count"] = len(emitted)

    return out


def _extract_direct_search(sabina, query: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "search_exists": callable(getattr(sabina, "search", None)),
        "rows": [],
        "errors": [],
    }

    search = getattr(sabina, "search", None)
    if not callable(search):
        return out

    started = time.monotonic()
    try:
        raw = search(query)
        rows = [] if raw is None else (raw if isinstance(raw, list) else list(raw))
        out["elapsed"] = round(time.monotonic() - started, 3)
        out["rows"] = rows
        out["count"] = len(rows)
    except Exception as exc:
        out["elapsed"] = round(time.monotonic() - started, 3)
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["traceback"] = traceback.format_exc()
        out["count"] = 0

    return out


def _trace_discovery(sabina, query: str) -> Dict[str, Any]:
    out = {
        "function_exists": callable(getattr(sabina, "_discover_from_first_party", None)),
        "urls": [],
    }
    fn = getattr(sabina, "_discover_from_first_party", None)
    if not callable(fn):
        return out

    try:
        requests = getattr(sabina, "requests", None)
        if requests is None:
            raise RuntimeError("Sabina module does not expose requests")

        session = requests.Session()
        try:
            headers = getattr(sabina, "HEADERS", None)
            if isinstance(headers, dict):
                session.headers.update(headers)

            started = time.monotonic()
            urls = fn(session, query)
            out["elapsed"] = round(time.monotonic() - started, 3)
            out["urls"] = list(urls or [])
            out["count"] = len(out["urls"])
        finally:
            session.close()

    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["traceback"] = traceback.format_exc()

    return out


def _trace_extraction_for_urls(
    sabina,
    query: str,
    urls: List[str],
) -> Dict[str, Any]:
    fn = getattr(sabina, "_extract_product_page", None)
    out = {
        "function_exists": callable(fn),
        "candidates": [],
    }

    if not callable(fn):
        return out

    for url in urls:
        item = {
            "url": url,
            "raw_rows": [],
            "status": "NOT_RUN",
            "error": None,
        }

        try:
            started = time.monotonic()
            rows = fn(url, query)
            item["elapsed"] = round(time.monotonic() - started, 3)
            if rows is None:
                rows = []
            elif not isinstance(rows, list):
                rows = list(rows)
            item["raw_rows"] = rows
            item["status"] = "SUCCESS" if rows else "FAILED_EMPTY"
            item["row_count"] = len(rows)
        except Exception as exc:
            item["status"] = "FAILED_EXCEPTION"
            item["error"] = f"{type(exc).__name__}: {exc}"
            item["traceback"] = traceback.format_exc()

        out["candidates"].append(item)

    return out


def _matcher_trace(main_module, rows: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
    out = {
        "product_matcher_loaded": getattr(main_module, "PRODUCT_MATCHER", None) is not None,
        "input_count": len(rows),
        "passed": [],
        "rejected": [],
        "errors": [],
    }

    matcher = getattr(main_module, "PRODUCT_MATCHER", None)
    if matcher is None:
        out["note"] = "PRODUCT_MATCHER unavailable in diagnostic process"
        return out

    for row in rows:
        raw = deepcopy(row)
        try:
            matched = matcher.match(raw, query)
            if matched is None:
                out["rejected"].append({
                    "input": raw,
                    "reason": "ProductMatcher.match returned None",
                })
            elif isinstance(matched, dict):
                out["passed"].append(matched)
            else:
                out["rejected"].append({
                    "input": raw,
                    "reason": f"unexpected matcher return type: {type(matched).__name__}",
                })
        except Exception as exc:
            out["errors"].append({
                "input": raw,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            })

    return out


def _clean_trace(main_module, rows: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
    out = {
        "input_count": len(rows),
        "passed": [],
        "rejected": [],
        "errors": [],
    }

    clean_result = getattr(main_module, "clean_result", None)
    if not callable(clean_result):
        out["error"] = "main.clean_result unavailable"
        return out

    for row in rows:
        raw = deepcopy(row)
        try:
            clean = clean_result(raw, "sabina", query)
            if clean is None:
                out["rejected"].append({
                    "input": raw,
                    "reason": "clean_result returned None",
                })
            else:
                out["passed"].append(clean)
        except Exception as exc:
            out["errors"].append({
                "input": raw,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            })

    return out


def _dedup_trace(main_module, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = {
        "input_count": len(rows),
        "kept": [],
        "dropped": [],
        "error": None,
    }

    dedupe = getattr(main_module, "dedupe_results", None)
    result_key = getattr(main_module, "result_key", None)

    if not callable(dedupe):
        out["error"] = "main.dedupe_results unavailable"
        return out

    try:
        if callable(result_key):
            groups = defaultdict(list)
            for idx, row in enumerate(rows):
                groups[str(result_key(row))].append({
                    "index": idx,
                    "row": row,
                })
            out["duplicate_groups_before"] = [
                group
                for group in groups.values()
                if len(group) > 1
            ]

        kept = dedupe(rows)
        out["kept"] = kept
        kept_ids = {id(x) for x in kept}
        # Since dedupe returns references to original dicts, identity is enough
        # to identify the dropped objects in this in-process diagnostic.
        for row in rows:
            if id(row) not in kept_ids:
                out["dropped"].append(row)
        out["kept_count"] = len(kept)
        out["dropped_count"] = len(out["dropped"])
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["traceback"] = traceback.format_exc()

    return out


def _variant_matrix(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    matrix = {}

    for expected in EXPECTED:
        evidence = []
        for row in rows:
            check = _candidate_matches_variant(row, expected)
            if check["exact"] or check["token_overlap"] >= 0.80:
                evidence.append({
                    "name": row.get("name"),
                    "canonical_name": row.get("canonical_name"),
                    "brand": row.get("brand"),
                    "url": row.get("url"),
                    "store_product_id": row.get("store_product_id"),
                    "size_ml": row.get("size_ml"),
                    "availability": row.get("availability"),
                    "token_overlap": check["token_overlap"],
                    "best_name": check["best_name"],
                })
        matrix[expected] = evidence

    return matrix


def _find_raw_variant_evidence(rows: List[Dict[str, Any]], expected: str) -> List[Dict[str, Any]]:
    found = []
    target = _norm(expected)
    target_tokens = set(target.split())

    for row in rows:
        text = _flatten_text(row)
        norm_text = _norm(text)
        score = len(target_tokens & set(norm_text.split())) / max(1, len(target_tokens))
        if target in norm_text or score >= 0.80:
            found.append({
                "name": row.get("name"),
                "title": row.get("title"),
                "source_name": (
                    row.get("source", {}).get("source_name")
                    if isinstance(row.get("source"), dict)
                    else None
                ),
                "brand": row.get("brand"),
                "url": row.get("url"),
                "store_product_id": row.get("store_product_id"),
                "size_ml": row.get("size_ml"),
                "availability": row.get("availability"),
                "token_overlap": round(score, 3),
            })

    return found


@router.get("/diagnose-sabina-born-in-roma")
def diagnose_sabina_born_in_roma(
    q: str = Query("Born in Roma")
):
    query = str(q or "").strip()
    started = time.monotonic()

    EXPECTED_BY_NORM.clear()
    EXPECTED_BY_NORM.update({_norm(x): x for x in EXPECTED})

    report: Dict[str, Any] = {
        "diagnostic": True,
        "diagnostic_name": "sabina_born_in_roma_forensic_v1",
        "query": query,
        "expected_count": len(EXPECTED),
        "expected": EXPECTED,
        "module": {},
        "production_architecture": {},
        "discovery": {},
        "extraction": {},
        "direct_search": {},
        "stream_search": {},
        "validation_clean_result": {},
        "product_matcher": {},
        "dedup": {},
        "final_production_simulation": {},
        "variant_matrix": {},
        "missing": [],
        "per_variant": {},
        "conclusion": None,
        "elapsed": 0.0,
    }

    try:
        try:
            import main as main_module
        except Exception:
            main_module = importlib.import_module("backend.main")

        report["production_architecture"]["main_file"] = getattr(
            main_module, "__file__", None
        )
        report["production_architecture"]["app_version"] = getattr(
            main_module, "APP_VERSION", None
        )

        try:
            sabina = importlib.import_module("scrapers.sabina.scraper")
        except Exception:
            sabina = importlib.import_module("backend.scrapers.sabina.scraper")

        report["module"] = {
            "file": getattr(sabina, "__file__", None),
            "BASE": getattr(sabina, "BASE", None),
            "MAX_CANDIDATES": getattr(sabina, "MAX_CANDIDATES", None),
            "PRODUCT_WORKERS": getattr(sabina, "PRODUCT_WORKERS", None),
            "search_exists": callable(getattr(sabina, "search", None)),
            "search_stream_exists": callable(getattr(sabina, "search_stream", None)),
            "_discover_from_first_party_exists": callable(
                getattr(sabina, "_discover_from_first_party", None)
            ),
            "_extract_product_page_exists": callable(
                getattr(sabina, "_extract_product_page", None)
            ),
        }

        # 1. Exact current discovery, with URLs retained.
        discovery = _trace_discovery(sabina, query)
        report["discovery"] = discovery

        discovered_urls = list(discovery.get("urls") or [])

        # 2. Direct current search() path.
        report["direct_search"] = _extract_direct_search(sabina, query)

        # 3. Current runtime streaming path. This is what main.py actually
        # calls when sitecustomize installed search_stream.
        stream = _extract_raw_stream(sabina, query)
        report["stream_search"] = stream

        # 4. Independently force every discovered URL through current extractor
        # so discovery and extraction are separable.
        extraction = _trace_extraction_for_urls(sabina, query, discovered_urls)
        report["extraction"] = extraction

        all_extracted_rows = []
        for candidate in extraction.get("candidates") or []:
            for row in candidate.get("raw_rows") or []:
                if isinstance(row, dict):
                    all_extracted_rows.append(row)

        # Include raw stream/direct rows for comparison.
        raw_direct_rows = [
            row for row in report["direct_search"].get("rows") or []
            if isinstance(row, dict)
        ]
        raw_stream_rows = [
            row for row in report["stream_search"].get("rows") or []
            if isinstance(row, dict)
        ]

        # 5. Main clean_result stage WITHOUT touching main.py.
        clean_trace = _clean_trace(main_module, all_extracted_rows, query)
        report["validation_clean_result"] = clean_trace

        # 6. ProductMatcher trace on exactly those extracted rows.
        matcher_input = list(all_extracted_rows)
        report["product_matcher"] = _matcher_trace(
            main_module,
            matcher_input,
            query,
        )

        # 7. Main's production dedupe on matcher-cleaned rows.
        cleaned_passed = [
            x for x in clean_trace.get("passed") or []
            if isinstance(x, dict)
        ]
        report["dedup"] = _dedup_trace(main_module, cleaned_passed)

        # 8. Simulate final main production assembly for Sabina:
        # search_stream -> clean_result -> dedupe. Direct search is included
        # as a comparative signal but is not substituted for the production
        # stream path.
        final_stream_cleaned = []
        for row in raw_stream_rows:
            try:
                clean = main_module.clean_result(row, "sabina", query)
            except Exception:
                clean = None
            if clean is not None:
                final_stream_cleaned.append(clean)

        try:
            final_stream_deduped = main_module.dedupe_results(final_stream_cleaned)
        except Exception:
            final_stream_deduped = final_stream_cleaned

        report["final_production_simulation"] = {
            "stream_raw_count": len(raw_stream_rows),
            "stream_cleaned_count": len(final_stream_cleaned),
            "stream_final_count": len(final_stream_deduped),
            "stream_final_rows": final_stream_deduped,
            "direct_raw_count": len(raw_direct_rows),
            "direct_raw_rows": raw_direct_rows,
        }

        # 9. Forensic matrix.
        report["variant_matrix"] = {
            "discovered_url_evidence": {
                expected: [
                    url
                    for url in discovered_urls
                    if expected.lower().replace(" ", "-") in url.lower()
                ]
                for expected in EXPECTED
            },
            "extracted_rows": {
                expected: _find_raw_variant_evidence(all_extracted_rows, expected)
                for expected in EXPECTED
            },
            "stream_rows": {
                expected: _find_raw_variant_evidence(raw_stream_rows, expected)
                for expected in EXPECTED
            },
            "clean_rows": {
                expected: _find_raw_variant_evidence(cleaned_passed, expected)
                for expected in EXPECTED
            },
            "final_rows": {
                expected: _find_raw_variant_evidence(final_stream_deduped, expected)
                for expected in EXPECTED
            },
        }

        # 10. Per-variant gate report.
        for expected in EXPECTED:
            url_hits = []
            extraction_hits = []
            raw_stream_hits = []
            clean_hits = []
            final_hits = []

            for url in discovered_urls:
                url_norm = _norm(url.replace("-", " "))
                expected_norm = _norm(expected)
                expected_tokens = set(expected_norm.split())
                overlap = len(expected_tokens & set(url_norm.split())) / max(
                    1, len(expected_tokens)
                )
                if expected_norm in url_norm or overlap >= 0.80:
                    url_hits.append(url)

            for row in all_extracted_rows:
                check = _candidate_matches_variant(row, expected)
                if check["exact"] or check["token_overlap"] >= 0.80:
                    extraction_hits.append(row)

            for row in raw_stream_rows:
                check = _candidate_matches_variant(row, expected)
                if check["exact"] or check["token_overlap"] >= 0.80:
                    raw_stream_hits.append(row)

            for row in cleaned_passed:
                check = _candidate_matches_variant(row, expected)
                if check["exact"] or check["token_overlap"] >= 0.80:
                    clean_hits.append(row)

            for row in final_stream_deduped:
                check = _candidate_matches_variant(row, expected)
                if check["exact"] or check["token_overlap"] >= 0.80:
                    final_hits.append(row)

            classification = "UNKNOWN"

            if final_hits:
                classification = "PRESENT"
            elif raw_stream_hits:
                classification = "LOST_AFTER_STREAM_CLEAN_OR_DEDUP"
            elif clean_hits:
                classification = "LOST_AFTER_DEDUP"
            elif extraction_hits:
                classification = "LOST_AT_CLEAN_OR_PRODUCT_MATCHER"
            elif url_hits:
                classification = "FOUND_DISCOVERY_BUT_EXTRACTION_EMPTY"
            else:
                classification = "NOT_DISCOVERED"

            report["per_variant"][expected] = {
                "discovery": {
                    "status": "FOUND" if url_hits else "NOT_FOUND",
                    "candidate_urls": url_hits,
                },
                "extraction": {
                    "status": "SUCCESS" if extraction_hits else "FAILED_OR_NO_MATCH",
                    "candidate_rows": extraction_hits,
                },
                "stream": {
                    "status": "FOUND" if raw_stream_hits else "NOT_FOUND",
                    "candidate_rows": raw_stream_hits,
                },
                "validation": {
                    "status": "PASS" if clean_hits else "FAIL",
                    "candidate_rows": clean_hits,
                },
                "dedup": {
                    "status": "KEPT" if final_hits else (
                        "DROPPED" if clean_hits else "N/A"
                    ),
                    "candidate_rows": final_hits,
                },
                "classification": classification,
            }

        missing = [
            expected
            for expected in EXPECTED
            if report["per_variant"][expected]["classification"] != "PRESENT"
        ]
        present = [x for x in EXPECTED if x not in missing]

        report["found_count"] = len(present)
        report["missing_count"] = len(missing)
        report["missing"] = missing

        counts = {
            "not_discovered": 0,
            "found_but_extraction_failed": 0,
            "lost_after_matching_or_validation": 0,
            "lost_after_dedup": 0,
            "present": 0,
        }

        for expected in EXPECTED:
            classification = report["per_variant"][expected]["classification"]
            if classification == "PRESENT":
                counts["present"] += 1
            elif classification == "NOT_DISCOVERED":
                counts["not_discovered"] += 1
            elif classification == "FOUND_DISCOVERY_BUT_EXTRACTION_EMPTY":
                counts["found_but_extraction_failed"] += 1
            elif classification == "LOST_AFTER_DEDUP":
                counts["lost_after_dedup"] += 1
            else:
                counts["lost_after_matching_or_validation"] += 1

        report["conclusion"] = {
            "counts": counts,
            "statement": (
                "Diagnosis complete. Inspect per_variant[].classification. "
                "No production file was modified by this diagnostic."
            ),
        }

    except Exception as exc:
        report["ok"] = False
        report["fatal_error"] = f"{type(exc).__name__}: {exc}"
        report["fatal_traceback"] = traceback.format_exc()
    finally:
        report["elapsed"] = round(time.monotonic() - started, 3)

    return _safe_json(report)
