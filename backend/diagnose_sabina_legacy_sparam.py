from __future__ import annotations

import inspect
import re
import time
from urllib.parse import quote, urljoin, urlparse

from fastapi import APIRouter, Query

router = APIRouter()

TARGET_TOKEN = "41708"
BASE_URL = "https://www.sabina.com/it/ricerca_old"


def _load_engine():
    import catalog_engine as ce
    return ce


def _extract_all_sabina_ids(data: bytes) -> list[str]:
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
            for product_id in re.findall(r"\b\d+\b", match.group(1)):
                ids.add(product_id)

    return sorted(ids, key=lambda value: int(value))


def _extract_product_ids(data: bytes) -> list[str]:
    return _extract_all_sabina_ids(data)


def _extract_pagination_urls(data: bytes, current_url: str) -> list[str]:
    """
    Read-only extraction of Sabina legacy-search pagination/navigation URLs.
    No product-specific token is used.
    """
    raw = data.decode("utf-8", "ignore")
    urls: set[str] = set()

    patterns = (
        r'''href=["']([^"']+)["']''',
        r'''data-url=["']([^"']+)["']''',
        r'''data-href=["']([^"']+)["']''',
        r'''data-next-url=["']([^"']+)["']''',
        r'''data-pagination-url=["']([^"']+)["']''',
    )

    for pattern in patterns:
        for match in re.finditer(pattern, raw, re.I):
            raw_url = match.group(1)
            absolute = urljoin(current_url, raw_url).split("#", 1)[0]

            parsed = urlparse(absolute)

            if parsed.netloc.lower() != "www.sabina.com":
                continue

            path = (parsed.path or "").lower()

            if "/ricerca_old" not in path:
                continue

            if "s=" not in parsed.query.lower():
                continue

            urls.add(absolute)

    return sorted(urls)


def _pagination_signature(url: str) -> str:
    """
    Normalize a pagination URL enough to avoid revisiting the same URL.
    The search term is preserved; only obvious tracking parameters are ignored.
    """
    parsed = urlparse(url)

    pairs = []
    for item in parsed.query.split("&"):
        if not item:
            continue
        key = item.split("=", 1)[0].lower()
        if key in {
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_content",
            "utm_term",
        }:
            continue
        pairs.append(item)

    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{'&'.join(sorted(pairs))}"


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
            "diagnostic": "sabina-legacy-sparam-v3",
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
            "diagnostic": "sabina-legacy-sparam-v3",
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
        "diagnostic": "sabina-legacy-sparam-v3",
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
    started = time.time()
    ce = _load_engine()

    search_url = f"{BASE_URL}?s={quote(q)}"

    http_fetch = getattr(ce, "_http_fetch", None)
    legacy = getattr(ce, "_sabina_legacy_product_urls", None)

    if http_fetch is None:
        return {
            "diagnostic": "sabina-500-limit-v1",
            "ok": False,
            "error": "catalog_engine._http_fetch not found",
            "read_only": True,
        }

    try:
        response = http_fetch(search_url, timeout=30)
        data = response.get("data") or b""

        all_ids = _extract_all_sabina_ids(data)

        helper_ids = (
            legacy(data, search_url)
            if legacy is not None
            else set()
        )

        helper_target_urls = [
            url for url in helper_ids
            if TARGET_TOKEN in url
        ]

        target_position = None
        for index, product_id in enumerate(all_ids, start=1):
            if product_id == TARGET_TOKEN:
                target_position = index
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
                "field_found": bool(all_ids),
                "total_ids_in_field": len(all_ids),
                "target_41708_position_1_based": target_position,
                "target_41708_within_first_500": (
                    target_position is not None
                    and target_position <= 500
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
                "TARGET_AFTER_500"
                if target_position is not None
                and target_position > 500
                else
                "TARGET_WITHIN_500_BUT_HELPER_LOST_IT"
                if target_position is not None
                and target_position <= 500
                and not helper_target_urls
                else
                "TARGET_PRESENT_AND_HELPER_SEES_IT"
                if TARGET_TOKEN in all_ids
                and helper_target_urls
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


@router.get("/diagnose-sabina-search-pagination")
def diagnose_sabina_search_pagination(
    q: str = Query("parfum"),
    max_pages: int = Query(10, ge=1, le=30),
):
    """
    Read-only pagination diagnostic.

    Starts from Sabina's native legacy search ?s=<query>, discovers only
    additional legacy-search pagination URLs, follows them, extracts all
    controller product IDs and stops immediately if 41708 is found.

    No production search, matcher, catalog write, hydration, resync or DB
    mutation is performed.
    """
    started = time.time()
    ce = _load_engine()

    http_fetch = getattr(ce, "_http_fetch", None)

    if http_fetch is None:
        return {
            "diagnostic": "sabina-search-pagination-v1",
            "ok": False,
            "error": "catalog_engine._http_fetch not found",
            "read_only": True,
        }

    first_url = f"{BASE_URL}?s={quote(q)}"

    queue = [first_url]
    queued = {_pagination_signature(first_url)}
    visited = set()

    pages = []
    all_ids: set[str] = set()
    target_pages = []

    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        signature = _pagination_signature(url)

        if signature in visited:
            continue

        visited.add(signature)

        try:
            response = http_fetch(url, timeout=30)
        except Exception as exc:
            pages.append({
                "url": url,
                "ok": False,
                "error": f"{type(exc).__name__}:{exc}",
            })
            continue

        data = response.get("data") or b""

        if not data:
            pages.append({
                "url": url,
                "ok": False,
                "status": response.get("status"),
                "bytes": 0,
            })
            continue

        ids = _extract_product_ids(data)

        before = len(all_ids)
        all_ids.update(ids)

        found_here = TARGET_TOKEN in ids

        if found_here:
            target_pages.append(url)

        pagination_urls = _extract_pagination_urls(
            data,
            response.get("url") or url,
        )

        new_pagination_urls = []

        for next_url in pagination_urls:
            next_signature = _pagination_signature(next_url)

            if next_signature in visited:
                continue

            if next_signature in queued:
                continue

            queued.add(next_signature)
            queue.append(next_url)
            new_pagination_urls.append(next_url)

        pages.append({
            "page_number": len(pages) + 1,
            "url": url,
            "ok": True,
            "status": response.get("status"),
            "bytes": len(data),
            "id_count": len(ids),
            "new_unique_ids": len(all_ids) - before,
            "target_found": found_here,
            "pagination_urls_found": len(pagination_urls),
            "new_pagination_urls": new_pagination_urls[:20],
            "sample_ids": ids[:10],
        })

        if found_here:
            break

    return {
        "diagnostic": "sabina-search-pagination-v1",
        "ok": True,
        "query": q,
        "seed": first_url,
        "limits": {
            "max_pages": max_pages,
        },
        "result": {
            "pages_visited": len(pages),
            "unique_ids_found": len(all_ids),
            "target_41708_found": TARGET_TOKEN in all_ids,
            "target_pages": target_pages,
            "remaining_queue": len(queue),
        },
        "pages": pages,
        "read_only": True,
        "production_search_called": False,
        "product_matcher_called": False,
        "database_written": False,
        "catalog_resync_called": False,
        "catalog_resync_called": False,
        "elapsed_sec": round(time.time() - started, 3),
    }
