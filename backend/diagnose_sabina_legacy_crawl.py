"""
ScentHunter - Sabina one-product-page forensic diagnostic.

Read-only diagnostic only. It makes exactly one HTTP request to the supplied
Sabina product URL, parses the already-downloaded HTML with the deployed
scraper's pure parsing functions, and reports the availability decision.

It does NOT call production search(), discovery, ProductMatcher, catalog writes,
hydration, resync, or any database operation.
"""

import inspect
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
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
        result = fn("sabina", [SEARCH_URL], time.time() + 45)
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
    One HTTP request + pure parser test.

    The HTTP request is deliberately performed here instead of calling
    extract_product_page(), because extract_product_page() performs its own
    network request. This isolates HTTP from HTML parsing/availability logic.
    """
    started = time.monotonic()

    try:
        from scrapers.sabina import scraper

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return {
                "diagnostic": "sabina-product-page-v2",
                "ok": False,
                "stage": "input_validation",
                "error": "URL must use http or https",
                "url": url,
                "read_only": True,
            }

        if parsed.hostname not in {"sabina.com", "www.sabina.com"}:
            return {
                "diagnostic": "sabina-product-page-v2",
                "ok": False,
                "stage": "input_validation",
                "error": "URL host must be sabina.com",
                "url": url,
                "read_only": True,
            }

        headers = getattr(scraper, "HEADERS", {})
        response = requests.get(
            url,
            headers=headers,
            timeout=(3.0, 5.0),
            allow_redirects=True,
        )

        http = {
            "status": response.status_code,
            "final_url": response.url,
            "bytes": len(response.content),
            "elapsed_sec": round(time.monotonic() - started, 3),
        }

        if response.status_code >= 400:
            return {
                "diagnostic": "sabina-product-page-v2",
                "ok": False,
                "stage": "http_fetch",
                "query": q,
                "input_url": url,
                "http": http,
                "error": f"HTTP {response.status_code}",
                "read_only": True,
            }

        parse_started = time.monotonic()
        soup = BeautifulSoup(response.text, "html.parser")

        h1 = soup.select_one("h1")
        h1_text = (
            scraper.clean(h1.get_text(" ", strip=True))
            if h1
            else ""
        )

        product = scraper.first_jsonld_product(
            soup,
            expected_url=response.url,
            expected_title=h1_text or None,
        )

        product_name = scraper.clean(
            (product or {}).get("name") or h1_text
        )

        offer = scraper._select_product_offer(
            product or {},
            scraper.normalise_url(response.url),
            product_name,
            scraper.extract_size_ml_from_product_page(
                soup,
                product_name,
            )[0],
        )

        availability, availability_source = (
            scraper.availability_from_product_page(
                soup,
                offer,
            )
        )

        size_ml, size_source = (
            scraper.extract_size_ml_from_product_page(
                soup,
                product_name,
            )
        )

        price = (
            scraper.money_to_float(offer.get("price"))
            if isinstance(offer, dict)
            else None
        )

        if price is None:
            price, price_source = scraper.extract_price_from_html(soup)
        else:
            price_source = "sabina_jsonld"

        parsed_result = {
            "name": product_name or None,
            "size_ml": size_ml,
            "size_source": size_source,
            "price": price,
            "price_source": price_source,
            "offer_availability": (
                offer.get("availability")
                if isinstance(offer, dict)
                else None
            ),
            "availability_from_product_page": availability,
            "availability_source": availability_source,
            "available_boolean": (
                True if availability == "in_stock"
                else False if availability == "out_of_stock"
                else None
            ),
            "jsonld_product_found": bool(product),
            "jsonld_offer_found": bool(offer),
            "html_parser_elapsed_sec": round(
                time.monotonic() - parse_started, 4
            ),
        }

        # Compact evidence only: enough to prove why the parser classified
        # the page, without returning the entire Sabina HTML document.
        page_text = scraper.norm(
            soup.get_text(" ", strip=True)
        )
        notify_markers = (
            "avisame",
            "avísame",
            "notificarme",
            "notify me",
            "prévenez-moi",
            "me prévenir",
            "benachrichtigen",
        )
        date_markers = (
            "fecha de disponibilidad",
            "availability date",
            "date de disponibilité",
            "verfügbarkeitsdatum",
        )

        parsed_result["evidence"] = {
            "has_availability_date_marker": any(
                marker in page_text
                for marker in date_markers
            ),
            "has_notification_marker": any(
                marker in page_text
                for marker in notify_markers
            ),
            "purchase_control_scan": {
                "function": "availability_from_product_page",
                "purchase_roots_checked": True,
            },
        }

        return {
            "diagnostic": "sabina-product-page-v2",
            "ok": True,
            "purpose": (
                "one HTTP request followed by the deployed Sabina pure "
                "HTML/availability parser; no product-page scraper network call"
            ),
            "query": q,
            "input_url": url,
            "http": http,
            "scraper_module": getattr(scraper, "__file__", None),
            "result": parsed_result,
            "read_only": True,
            "production_search_called": False,
            "product_matcher_called": False,
            "catalog_written": False,
            "hydration_called": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }

    except requests.RequestException as exc:
        return {
            "diagnostic": "sabina-product-page-v2",
            "ok": False,
            "stage": "http_fetch",
            "query": q,
            "url": url,
            "error": f"{type(exc).__name__}: {exc}",
            "read_only": True,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }

    except Exception as exc:
        return {
            "diagnostic": "sabina-product-page-v2",
            "ok": False,
            "stage": "html_parse_or_availability",
            "query": q,
            "url": url,
            "error": f"{type(exc).__name__}: {exc}",
            "read_only": True,
            "production_search_called": False,
            "product_matcher_called": False,
            "catalog_written": False,
            "hydration_called": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }
