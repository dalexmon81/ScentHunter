from __future__ import annotations

import inspect
import re
import time
from urllib.parse import quote

from fastapi import APIRouter, Query

router = APIRouter()

TARGET_TOKEN = "41708"

BASE_URL = "https://www.sabina.com/it/ricerca_old"


def _load_engine():
    import catalog_engine as ce
    return ce


def _extract_all_sabina_ids(data: bytes) -> list[str]:
    """
    Read-only diagnostic parser.

    Deliberately does NOT call the production helper, because the purpose
    of this endpoint is to determine whether the helper's [:500] limit
    hides product 41708.
    """
    raw = data.decode("utf-8", "ignore")
    ids: set[str] = set()

    patterns = (
        r'id=["\']af_controller_product_ids["\'][^>]*'
        r'name=["\']af_controller_product_ids["\'][^>]*'
        r'value=["\']([^"\']*)["\']',

        r'name=["\']af_controller_product_ids["\'][^>]*'
        r'id=["\']af_controller_product_ids["\'][^>]*'
        r'value=["\']([^"\']*)["\']',

        r'id=["\']af_controller_product_ids["\'][^>]*'
        r'value=["\']([^"\']*)["\']',

        r'name=["\']af_controller_product_ids["\'][^>]*'
        r'value=["\']([^"\']*)["\']',
    )

    for pattern in patterns:
        for match in re.finditer(pattern, raw, re.I | re.S):
            value = match.group(1)
            for product_id in re.findall(r"\b\d+\b", value):
                ids.add(product_id)

    return sorted(ids, key=lambda value: int(value))


def _find_target_position(data: bytes) -> dict:
    raw = data.decode("utf-8", "ignore")

    patterns = (
        r'id=["\']af_controller_product_ids["\'][^>]*'
        r'name=["\']af_controller_product_ids["\'][^>]*'
        r'value=["\']([^"\']*)["\']',

        r'name=["\']af_controller_product_ids["\'][^>]*'
        r'id=["\']af_controller_product_ids["\'][^>]*'
        r'value=["\']([^"\']*)["\']',

        r'id=["\']af_controller_product_ids["\'][^>]*'
        r'value=["\']([^"\']*)["\']',

        r'name=["\']af_controller_product_ids["\'][^>]*'
        r'value=["\']([^"\']*)["\']',
    )

    for pattern in patterns:
        match = re.search(pattern, raw, re.I | re.S)
        if not match:
            continue

        value = match.group(1)
        ids = re.findall(r"\b\d+\b", value)

        for index, product_id in enumerate(ids, start=1):
            if product_id == TARGET_TOKEN:
                return {
                    "field_found": True,
                    "position_1_based": index,
                    "position_0_based": index - 1,
                    "within_first_500": index <= 500,
                    "field_id_count": len(ids),
                }

        return {
            "field_found": True,
            "position_1_based": None,
            "position_0_based": None,
            "within_first_500": False,
            "field_id_count": len(ids),
        }

    return {
        "field_found": False,
        "position_1_based": None,
        "position_0_based": None,
        "within_first_500": False,
        "field_id_count": 0,
    }


@router.get("/diagnose-sabina-legacy-sparam")
def diagnose_sabina_legacy_sparam(
    q: str = Query("liquid"),
):
    started = time.time()
    ce = _load_engine()

    fn = getattr(ce, "_discover_html_catalog", None)
    legacy = getattr(ce, "_sabina_legacy_product_urls", None)

    if fn is None:
        return {
            "diagnostic": "sabina-legacy-sparam-v2",
            "ok": False,
            "error": "catalog_engine._discover_html_catalog not found",
            "read_only": True,
        }

    search_url = f"{BASE_URL}?s={quote(q)}"

    old_pages = getattr(ce, "HTML_MAX_PAGES", None)
    old_depth = getattr(ce, "HTML_MAX_DEPTH", None)

    try:
        ce.HTML_MAX_PAGES = 1
        ce.HTML_MAX_DEPTH = 0

        result = fn(
            "sabina",
            [search_url],
            time.time() + 45,
        )

    except Exception as exc:
        return {
            "diagnostic": "sabina-legacy-sparam-v2",
            "ok": False,
            "query": q,
            "seed": search_url,
            "error": f"{type(exc).__name__}:{exc}",
            "read_only": True,
            "production_search_called": False,
            "product_matcher_called": False,
            "database_written": False,
            "catalog_resync_called": False,
            "elapsed_sec": round(time.time() - started, 3),
        }

    finally:
        if old_pages is not None:
            ce.HTML_MAX_PAGES = old_pages

        if old_depth is not None:
            ce.HTML_MAX_DEPTH = old_depth

    product_urls = sorted(
        (result.get("product_urls") or {}).keys()
    )

    target_urls = [
        url for url in product_urls
        if TARGET_TOKEN in url
    ]

    return {
        "diagnostic": "sabina-legacy-sparam-v2",
        "ok": True,

        "query": q,
        "seed": search_url,

        "source_flags": {
            "discover_html_catalog_exists": True,
            "legacy_helper_exists": bool(legacy),
            "discover_calls_legacy_helper": (
                "_sabina_legacy_product_urls"
                in inspect.getsource(fn)
            ),
        },

        "discovery_result": {
            "visited": result.get("visited"),
            "successes": result.get("successes"),
            "error_count": len(result.get("errors") or []),
            "errors": (result.get("errors") or [])[:10],
            "product_url_count": len(product_urls),
            "target_urls": target_urls,
            "target_found": bool(target_urls),
        },

        "sample_product_urls": product_urls[:50],

        "read_only": True,
        "production_search_called": False,
        "product_matcher_called": False,
        "database_written": False,
        "catalog_resync_called": False,

        "elapsed_sec": round(time.time() - started, 3),
    }


@router.get("/diagnose-sabina-500-limit")
def diagnose_sabina_500_limit(
    q: str = Query("perfume"),
):
    """
    Read-only diagnostic.

    Fetches Sabina's legacy search page directly and independently checks
    the complete af_controller_product_ids field.

    It then compares that complete field with the production helper's
    current [:500] behavior.

    No production search, matcher, catalog write, resync, or database write
    is performed.
    """
    started = time.time()
    ce = _load_engine()

    search_url = f"{BASE_URL}?s={quote(q)}"

    http_fetch = getattr(ce, "_http_fetch", None)
    legacy = getattr(ce, "_sabina_legacy_product_urls", None)

    if http_fetch is None:
        return {
            "diagnostic": "sabina-500-limit-v1",
            "ok": False,
            "query": q,
            "seed": search_url,
            "error": "catalog_engine._http_fetch not found",
            "read_only": True,
        }

    try:
        response = http_fetch(
            search_url,
            timeout=30,
        )

        data = response.get("data") or b""

        field_diag = _find_target_position(data)
        all_ids = _extract_all_sabina_ids(data)

        helper_ids = (
            sorted(
                (
                    legacy(data, search_url)
                    if legacy is not None
                    else set()
                ),
                key=lambda value: int(
                    re.search(r"id_product=(\d+)", value).group(1)
                )
                if re.search(r"id_product=(\d+)", value)
                else 0,
            )
            if legacy is not None
            else []
        )

        helper_target_urls = [
            url for url in helper_ids
            if TARGET_TOKEN in url
        ]

        target_position_from_all_ids = None

        for index, product_id in enumerate(all_ids, start=1):
            if product_id == TARGET_TOKEN:
                target_position_from_all_ids = index
                break

        return {
            "diagnostic": "sabina-500-limit-v1",
            "ok": True,
            "query": q,
            "seed": search_url,

            "http": {
                "status": response.get("status"),
                "bytes": len(data),
                "content_type": response.get("content_type"),
                "final_url": response.get("url"),
            },

            "raw_catalog_field": {
                "field_found": field_diag["field_found"],
                "total_ids_in_field": field_diag["field_id_count"],
                "target_41708_position_1_based": (
                    target_position_from_all_ids
                    or field_diag["position_1_based"]
                ),
                "target_41708_within_first_500": (
                    (
                        target_position_from_all_ids <= 500
                    )
                    if target_position_from_all_ids is not None
                    else False
                ),
                "target_41708_in_complete_id_list": (
                    TARGET_TOKEN in all_ids
                ),
                "first_10_ids": all_ids[:10],
                "last_10_ids": all_ids[-10:],
            },

            "production_helper_behavior": {
                "helper_exists": bool(legacy),
                "helper_return_count": len(helper_ids),
                "helper_contains_41708": bool(helper_target_urls),
                "helper_target_urls": helper_target_urls,
                "helper_uses_500_limit": (
                    "[:500]"
                    in inspect.getsource(legacy)
                    if legacy is not None
                    else None
                ),
            },

            "diagnosis": (
                "TARGET_AFTER_500: 41708 exists in Sabina's complete "
                "catalog field but is outside the first 500 IDs."
                if TARGET_TOKEN in all_ids
                and target_position_from_all_ids is not None
                and target_position_from_all_ids > 500
                else
                "TARGET_WITHIN_500_BUT_HELPER_LOST_IT"
                if TARGET_TOKEN in all_ids
                and target_position_from_all_ids is not None
                and target_position_from_all_ids <= 500
                and not helper_target_urls
                else
                "TARGET_PRESENT_AND_HELPER_SEES_IT"
                if TARGET_TOKEN in all_ids
                and bool(helper_target_urls)
                else
                "TARGET_NOT_IN_RAW_FIELD"
            ),

            "read_only": True,
            "production_search_called": False,
            "product_matcher_called": False,
            "database_written": False,
            "catalog_resync_called": False,

            "elapsed_sec": round(time.time() - started, 3),
        }

    except Exception as exc:
        return {
            "diagnostic": "sabina-500-limit-v1",
            "ok": False,
            "query": q,
            "seed": search_url,
            "error": f"{type(exc).__name__}:{exc}",
            "read_only": True,
            "production_search_called": False,
            "product_matcher_called": False,
            "database_written": False,
            "catalog_resync_called": False,
            "elapsed_sec": round(time.time() - started, 3),
        }
