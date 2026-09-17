from __future__ import annotations

import inspect
import re
import time
from typing import Any, Dict, List
from urllib.parse import quote_plus

from fastapi import APIRouter, Query

import main

router = APIRouter()

VERSION = "easycosmetic_only_v2"
MAX_SECONDS = 60
MAX_TESTED = 60


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _safe_call(fn, *args, default=None):
    try:
        return fn(*args)
    except Exception:
        return default


def _matching_text(product: Dict[str, Any]) -> str:
    fn = getattr(main, "_matching_text", None)
    if callable(fn):
        return _clean(fn(product))

    parts: List[str] = []
    for key in (
        "name", "title", "product_name", "brand", "source_brand",
        "product_line", "variant", "url"
    ):
        value = product.get(key)
        if value:
            parts.append(str(value))

    source = product.get("source")
    if isinstance(source, dict):
        for key in (
            "name", "title", "product_name", "brand",
            "source_brand", "product_line", "variant", "url"
        ):
            value = source.get(key)
            if value:
                parts.append(str(value))

    return _clean(" ".join(parts))


def _tokens(value: str) -> List[str]:
    fn = getattr(main, "_matching_tokens", None)
    if callable(fn):
        return list(_safe_call(fn, value, default=[]))
    return _clean(value).lower().split()


def _generic_match(product: Dict[str, Any], query: str):
    fn = getattr(main, "_generic_match", None)
    if callable(fn):
        return bool(_safe_call(fn, product, query, default=False))
    return None


def _product_size(product: Dict[str, Any]):
    fn = getattr(main, "product_size_ml", None)
    if callable(fn):
        return _safe_call(fn, product, default=None)
    return None


def _has_small_size(product: Dict[str, Any]):
    fn = getattr(main, "has_small_size", None)
    if callable(fn):
        return bool(_safe_call(fn, product, default=False))
    return None


def _concentration(value: Any):
    fn = getattr(main, "product_concentration", None)
    if callable(fn):
        return _safe_call(fn, value, default="")
    return ""


def _norm(value: Any) -> str:
    fn = getattr(main, "norm", None)
    if callable(fn):
        return _clean(_safe_call(fn, value, default=""))
    return _clean(value).lower()


def _non_perfume_hits(matching_text: str, query: str) -> List[str]:
    phrases = getattr(main, "NON_PERFUME", ())
    normalized_text = _norm(matching_text)
    normalized_query = _norm(query)
    hits = []

    for phrase in phrases:
        phrase_normalized = _norm(phrase)
        if (
            phrase_normalized
            and phrase_normalized in normalized_text
            and phrase_normalized not in normalized_query
        ):
            hits.append(phrase_normalized)

    return hits


def _explain(product: Dict[str, Any], query: str) -> Dict[str, Any]:
    name = _clean(
        product.get("name")
        or product.get("title")
        or product.get("product_name")
    )

    source = product.get("source")
    if isinstance(source, dict) and not name:
        name = _clean(
            source.get("name")
            or source.get("title")
            or source.get("product_name")
        )

    matching_text = _matching_text(product)
    query_normalized = _norm(query)

    query_has_size = bool(
        re.search(
            r"(?<!\d)\d+(?:[.,]\d+)?\s*(?:ml|cl)\b",
            query_normalized,
        )
    )

    size_ml = _product_size(product)
    small_size = _has_small_size(product)

    requested_concentration = _concentration({"name": query})
    candidate_concentration = _concentration(product)

    concentration_conflict = bool(
        requested_concentration
        and candidate_concentration
        and requested_concentration != candidate_concentration
    )

    non_perfume_hits = _non_perfume_hits(matching_text, query)

    query_tokens = _tokens(query)
    candidate_tokens = _tokens(matching_text)

    generic_match = _generic_match(product, query)

    # Reproduce the current matches() decision order explicitly.
    reasons: List[str] = []

    if not name and not matching_text:
        reasons.append("NO_NAME_AND_NO_MATCHING_TEXT")
    elif small_size and not query_has_size:
        reasons.append("SMALL_SIZE_REJECT")
    elif concentration_conflict:
        reasons.append("CONCENTRATION_CONFLICT")
    elif non_perfume_hits:
        reasons.append("NON_PERFUME_MARKER")
    elif generic_match is False:
        reasons.append("GENERIC_MATCH_FALSE")
    elif generic_match is None:
        reasons.append("GENERIC_MATCH_NOT_AVAILABLE_IN_DIAGNOSTIC")

    real_matches = bool(_safe_call(main.matches, product, query, default=False))

    return {
        "name": name,
        "brand": _clean(product.get("brand")),
        "size_ml": size_ml,
        "concentration": candidate_concentration,
        "url": _clean(product.get("url")),
        "matching_text": matching_text,
        "query_tokens": query_tokens,
        "candidate_tokens": candidate_tokens,
        "query_has_size": query_has_size,
        "small_size": small_size,
        "requested_concentration": requested_concentration,
        "candidate_concentration": candidate_concentration,
        "concentration_conflict": concentration_conflict,
        "non_perfume_hits": non_perfume_hits,
        "generic_match": generic_match,
        "real_matches": real_matches,
        "predicted_rejection_reason": reasons[0] if reasons else None,
    }


@router.get("/diagnose-easycosmetic")
def diagnose_easycosmetic(
    q: str = Query("Liquid Brun", min_length=1)
):
    started = time.monotonic()
    query = _clean(q)

    report: Dict[str, Any] = {
        "diagnostic": True,
        "version": VERSION,
        "query": query,
        "elapsed_sec": 0,
        "attempts": [],
        "raw": 0,
        "unique": 0,
        "tested": 0,
        "accepted": 0,
        "rejection_counts": {},
        "candidates": [],
        "errors": [],
        "deadline_sec": MAX_SECONDS,
        "matches_source": None,
    }

    try:
        source = inspect.getsource(main.matches)
        report["matches_source"] = source
    except Exception:
        report["matches_source"] = None

    try:
        attempts = main.build_search_attempts(query)
        report["attempts"] = list(attempts)
    except Exception as exc:
        report["errors"].append({
            "stage": "build_search_attempts",
            "error": f"{type(exc).__name__}: {exc}",
        })
        report["elapsed_sec"] = round(time.monotonic() - started, 3)
        return report

    scraper = None
    try:
        scraper = main.load_scraper("easycosmetic")
    except Exception as exc:
        report["errors"].append({
            "stage": "load_scraper",
            "error": f"{type(exc).__name__}: {exc}",
        })
        report["elapsed_sec"] = round(time.monotonic() - started, 3)
        return report

    search_fn = getattr(scraper, "search", None)
    scrape_fn = getattr(scraper, "scrape", None)
    fn = search_fn or scrape_fn

    if not callable(fn):
        report["errors"].append({
            "stage": "scraper",
            "error": "Easycosmetic scraper has neither search() nor scrape()",
        })
        report["elapsed_sec"] = round(time.monotonic() - started, 3)
        return report

    raw_candidates: List[Dict[str, Any]] = []

    for attempt in attempts:
        if time.monotonic() - started >= MAX_SECONDS:
            break

        try:
            rows = fn(attempt)
            if rows:
                raw_candidates.extend(
                    row for row in rows
                    if isinstance(row, dict)
                )
        except Exception as exc:
            report["errors"].append({
                "stage": "discovery",
                "attempt": attempt,
                "error": f"{type(exc).__name__}: {exc}",
            })

    report["raw"] = len(raw_candidates)

    # Same identity de-duplication used by the backend.
    unique: List[Dict[str, Any]] = []
    seen = set()

    for product in raw_candidates:
        try:
            key = main.product_identity_key(product)
        except Exception:
            key = (
                _clean(product.get("shop")),
                _clean(product.get("name")),
                _clean(product.get("url")),
            )

        if key in seen:
            continue

        seen.add(key)
        unique.append(product)

    report["unique"] = len(unique)

    # CRITICAL: test the already-discovered candidates immediately.
    # We do NOT call parse_product() again here.
    for product in unique:
        if time.monotonic() - started >= MAX_SECONDS:
            break

        if report["tested"] >= MAX_TESTED:
            break

        report["tested"] += 1

        try:
            explanation = _explain(product, query)

            if explanation["real_matches"]:
                report["accepted"] += 1

            reason = explanation["predicted_rejection_reason"]
            if explanation["real_matches"]:
                reason = "ACCEPTED"
            elif not reason:
                reason = "MATCHES_FALSE_WITHOUT_PREDICTED_GUARD"

            report["rejection_counts"][reason] = (
                report["rejection_counts"].get(reason, 0) + 1
            )

            # Keep useful candidates, especially anything containing
            # the requested identity tokens.
            text_lower = _norm(
                f"{explanation['name']} {explanation['url']}"
            )
            interesting = (
                "liquid" in text_lower
                or "brun" in text_lower
                or explanation["real_matches"]
            )

            if interesting or len(report["candidates"]) < 20:
                report["candidates"].append(explanation)

        except Exception as exc:
            report["errors"].append({
                "stage": "candidate_test",
                "index": report["tested"],
                "error": f"{type(exc).__name__}: {exc}",
            })

    report["elapsed_sec"] = round(time.monotonic() - started, 3)
    return report
