from __future__ import annotations

"""
ScentHunter - read-only one-page Sabina catalog-discovery handoff diagnostic.

This deliberately runs the production _discover_html_catalog() against ONE
known Sabina legacy-search URL only. It temporarily limits the generic crawler
to one page and restores the module globals afterwards.

No production search, matcher, resync, catalog write, or DB write is called.
"""

import inspect
import time
from fastapi import APIRouter, Query

router = APIRouter()

SEARCH_URL = "https://www.sabina.com/it/ricerca_old?search_query=Liquid+Brun"
TARGET_TOKEN = "41708"
TARGET_URL = "https://www.sabina.com/it/profumi-di-donna/41708-liquid-brun-limited-edition-extrait-de-parfum.html"


def _load_engine():
    import catalog_engine as ce
    return ce


@router.get("/diagnose-sabina-legacy-crawl")
def diagnose_sabina_legacy_crawl(
    max_pages: int = Query(1, ge=1, le=2),
    max_depth: int = Query(0, ge=0, le=1),
):
    started = time.time()
    ce = _load_engine()

    fn = getattr(ce, "_discover_html_catalog", None)
    legacy = getattr(ce, "_sabina_legacy_product_urls", None)
    priority = getattr(ce, "_html_discovery_priority", None)

    source = inspect.getsource(fn) if fn is not None else ""
    source_flags = {
        "discover_html_catalog_exists": bool(fn),
        "legacy_helper_exists": bool(legacy),
        "discover_calls_legacy_helper": "_sabina_legacy_product_urls" in source,
        "discover_has_anchor_product_extraction": "_html_product_url(store,href,page_base)" in source,
        "discover_has_embedded_url_extraction": "embedded_urls" in source,
        "priority_exists": bool(priority),
        "priority_mentions_ricerca_old": "ricerca_old" in (inspect.getsource(priority) if priority else ""),
    }

    if fn is None:
        return {
            "diagnostic": "sabina-legacy-crawl-v1",
            "ok": False,
            "error": "catalog_engine._discover_html_catalog not found",
            "read_only": True,
        }

    old_pages = getattr(ce, "HTML_MAX_PAGES", None)
    old_depth = getattr(ce, "HTML_MAX_DEPTH", None)
    try:
        ce.HTML_MAX_PAGES = int(max_pages)
        ce.HTML_MAX_DEPTH = int(max_depth)
        result = fn(
            "sabina",
            [SEARCH_URL],
            time.time() + 45,
        )
    finally:
        if old_pages is not None:
            ce.HTML_MAX_PAGES = old_pages
        if old_depth is not None:
            ce.HTML_MAX_DEPTH = old_depth

    product_urls = sorted((result.get("product_urls") or {}).keys())
    target_urls = [u for u in product_urls if TARGET_TOKEN in u or TARGET_URL.casefold() in u.casefold()]

    return {
        "diagnostic": "sabina-legacy-crawl-v1",
        "ok": True,
        "seed": SEARCH_URL,
        "limits": {"max_pages": max_pages, "max_depth": max_depth},
        "source_flags": source_flags,
        "discovery_result": {
            "visited": result.get("visited"),
            "successes": result.get("successes"),
            "error_count": len(result.get("errors") or []),
            "errors": (result.get("errors") or [])[:10],
            "product_url_count": len(product_urls),
            "target_urls": target_urls,
            "target_found": bool(target_urls),
        },
        "sample_product_urls": product_urls[:30],
        "read_only": True,
        "production_search_called": False,
        "product_matcher_called": False,
        "database_written": False,
        "catalog_resync_called": False,
        "elapsed_sec": round(time.time() - started, 3),
    }
