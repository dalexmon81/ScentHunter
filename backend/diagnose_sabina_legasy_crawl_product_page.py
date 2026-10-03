"""
ScentHunter - read-only Sabina catalog-discovery handoff diagnostic.

This module deliberately runs only bounded, read-only diagnostics.
It does not call production search(), ProductMatcher, catalog writes,
hydration, resync, or database writes.
"""

import inspect
import time
from urllib.parse import quote

import requests
from fastapi import APIRouter, Query

router = APIRouter()

SEARCH_URL = "https://www.sabina.com/it/ricerca_old?search_query=Liquid+Brun"
TARGET_TOKEN = "41708"
TARGET_URL = (
    "https://www.sabina.com/it/profumi-di-donna/"
    "41708-liquid-brun-limited-edition-extrait-de-parfum.html"
)

DEFAULT_PRODUCT_URL = (
    "https://www.sabina.com/it/profumi-da-uomo/"
    "34982-liquid-brun-eau-de-parfum-french-avenue.html"
)


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
        "discover_has_anchor_product_extraction":
            "_html_product_url(store,href,page_base)" in source,
        "discover_has_embedded_url_extraction": "embedded_urls" in source,
        "priority_exists": bool(priority),
        "priority_mentions_ricerca_old":
            "ricerca_old" in (inspect.getsource(priority) if priority else ""),
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
    target_urls = [
        u for u in product_urls
        if TARGET_TOKEN in u or TARGET_URL.casefold() in u.casefold()
    ]

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


@router.get("/diagnose-sabina-product-page")
def diagnose_sabina_product_page(
    url: str = Query(DEFAULT_PRODUCT_URL, min_length=20, max_length=1000),
    q: str = Query("Liquid Brun", min_length=1, max_length=120),
):
    """
    Read-only forensic test of ONE real Sabina product page.

    It calls the deployed scraper's extract_product_page() directly.
    It does not run discovery, production search, matcher, catalog writes,
    hydration, or resync. The purpose is to prove exactly what the scraper
    emits for offer.availability / available / provenance.availability.
    """
    started = time.monotonic()

    try:
        from scrapers.sabina import scraper

        parsed = requests.utils.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return {
                "diagnostic": "sabina-product-page-v1",
                "ok": False,
                "stage": "input_validation",
                "error": "URL must use http or https",
                "url": url,
                "read_only": True,
            }

        if parsed.hostname not in {"sabina.com", "www.sabina.com"}:
            return {
                "diagnostic": "sabina-product-page-v1",
                "ok": False,
                "stage": "input_validation",
                "error": "URL host must be sabina.com",
                "url": url,
                "read_only": True,
            }

        session = requests.Session()
        try:
            response_probe = session.get(
                url,
                headers=getattr(scraper, "HEADERS", {}),
                timeout=getattr(scraper, "TIMEOUT", 7),
                allow_redirects=True,
            )
            probe = {
                "status": response_probe.status_code,
                "final_url": response_probe.url,
                "bytes": len(response_probe.content),
            }

            if response_probe.status_code >= 400:
                return {
                    "diagnostic": "sabina-product-page-v1",
                    "ok": False,
                    "stage": "http_fetch",
                    "query": q,
                    "url": url,
                    "probe": probe,
                    "error": f"HTTP {response_probe.status_code}",
                    "read_only": True,
                    "elapsed_sec": round(time.monotonic() - started, 3),
                }

            row = scraper.extract_product_page(session, url, q)

            return {
                "diagnostic": "sabina-product-page-v1",
                "ok": True,
                "purpose": (
                    "read-only execution of the deployed Sabina "
                    "extract_product_page() on one product URL"
                ),
                "query": q,
                "input_url": url,
                "http_probe": probe,
                "scraper_module": getattr(scraper, "__file__", None),
                "scraper_function": "extract_product_page",
                "result": {
                    "store": row.get("store") if isinstance(row, dict) else None,
                    "source": row.get("source") if isinstance(row, dict) else None,
                    "identity": row.get("identity") if isinstance(row, dict) else None,
                    "attributes": row.get("attributes") if isinstance(row, dict) else None,
                    "offer": row.get("offer") if isinstance(row, dict) else None,
                    "available": row.get("available") if isinstance(row, dict) else None,
                    "availability": (
                        row.get("availability")
                        if isinstance(row, dict)
                        else None
                    ),
                    "provenance": (
                        row.get("provenance")
                        if isinstance(row, dict)
                        else None
                    ),
                },
                "read_only": True,
                "production_search_called": False,
                "product_matcher_called": False,
                "catalog_written": False,
                "hydration_called": False,
                "elapsed_sec": round(time.monotonic() - started, 3),
            }
        finally:
            session.close()

    except Exception as exc:
        return {
            "diagnostic": "sabina-product-page-v1",
            "ok": False,
            "query": q,
            "url": url,
            "stage": "extract_product_page",
            "error": f"{type(exc).__name__}: {exc}",
            "read_only": True,
            "production_search_called": False,
            "product_matcher_called": False,
            "catalog_written": False,
            "hydration_called": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }
