"""
ScentHunter - Sabina bounded discovery diagnostic v3.

Read-only. This module isolates Sabina native discovery routes without calling
search(), product pages, ProductMatcher, catalog, hydration, or aggregation.
It also preserves the existing product-page availability diagnostic.
"""

import inspect
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, Query

router = APIRouter()

DEFAULT_PRODUCT_URL = (
    "https://www.sabina.com/it/profumi-da-uomo/"
    "34982-liquid-brun-eau-de-parfum-french-avenue.html"
)

SEARCH_ENDPOINTS = (
    ("it_ricerca", "https://www.sabina.com/it/ricerca", {"controller": "search", "s": True}),
    ("it_search", "https://www.sabina.com/it/search", {"controller": "search", "s": True}),
    ("es_buscar", "https://www.sabina.com/es/buscar", {"search_query": True}),
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.sabina.com/es/",
}


def _load_scraper():
    from scrapers.sabina import scraper
    return scraper


@router.get("/diagnose-sabina-discovery")
def diagnose_sabina_discovery(
    q: str = Query("Liquid Brun", min_length=1, max_length=120),
):
    """Run each Sabina native-search route independently and report candidates."""
    started = time.monotonic()
    scraper = _load_scraper()
    query = scraper.clean(q)
    rows = []

    session = requests.Session()
    try:
        for name, endpoint, template in SEARCH_ENDPOINTS:
            params = {k: (query if v is True else v) for k, v in template.items()}
            item_started = time.monotonic()
            try:
                response = session.get(
                    endpoint,
                    params=params,
                    headers=getattr(scraper, "HEADERS", HEADERS),
                    timeout=(3.0, 7.0),
                    allow_redirects=True,
                )
                final_url = response.url
                candidates = []
                if response.status_code < 400:
                    candidates = scraper._extract_search_candidates(response, query)

                rows.append({
                    "route": name,
                    "request_url": response.url,
                    "status": response.status_code,
                    "final_url": final_url,
                    "bytes": len(response.content),
                    "candidate_count": len(candidates),
                    "liquid_brun_candidates": [
                        u for u in candidates[:50]
                        if scraper.query_matches(u, query)
                    ][:20],
                    "sample_candidates": candidates[:20],
                    "elapsed_sec": round(time.monotonic() - item_started, 3),
                })
            except requests.RequestException as exc:
                rows.append({
                    "route": name,
                    "request_url": endpoint,
                    "status": None,
                    "final_url": None,
                    "bytes": 0,
                    "candidate_count": 0,
                    "liquid_brun_candidates": [],
                    "sample_candidates": [],
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_sec": round(time.monotonic() - item_started, 3),
                })
    finally:
        session.close()

    return {
        "diagnostic": "sabina-discovery-v3",
        "ok": True,
        "query": query,
        "purpose": "bounded native discovery only; one request per Sabina native route",
        "routes": rows,
        "interpretation": {
            "candidate_source": "_extract_search_candidates",
            "product_pages_called": False,
            "search_called": False,
            "product_matcher_called": False,
            "catalog_written": False,
            "hydration_called": False,
        },
        "read_only": True,
        "elapsed_sec": round(time.monotonic() - started, 3),
    }


@router.get("/diagnose-sabina-product-page")
def diagnose_sabina_product_page(
    url: str = Query(DEFAULT_PRODUCT_URL, min_length=20, max_length=1000),
    q: str = Query("Liquid Brun", min_length=1, max_length=120),
):
    """One HTTP request + pure parser test for product-page availability."""
    started = time.monotonic()
    try:
        scraper = _load_scraper()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return {"diagnostic": "sabina-product-page-v3", "ok": False, "stage": "input_validation", "error": "URL must use http or https", "read_only": True}
        if parsed.hostname not in {"sabina.com", "www.sabina.com"}:
            return {"diagnostic": "sabina-product-page-v3", "ok": False, "stage": "input_validation", "error": "URL host must be sabina.com", "read_only": True}

        response = requests.get(
            url,
            headers=getattr(scraper, "HEADERS", HEADERS),
            timeout=(3.0, 7.0),
            allow_redirects=True,
        )
        http = {
            "status": response.status_code,
            "final_url": response.url,
            "bytes": len(response.content),
            "elapsed_sec": round(time.monotonic() - started, 3),
        }
        if response.status_code >= 400:
            return {"diagnostic": "sabina-product-page-v3", "ok": False, "stage": "http_fetch", "query": q, "input_url": url, "http": http, "error": f"HTTP {response.status_code}", "read_only": True}

        parse_started = time.monotonic()
        soup = BeautifulSoup(response.text, "html.parser")
        h1 = soup.select_one("h1")
        h1_text = scraper.clean(h1.get_text(" ", strip=True)) if h1 else ""
        product = scraper.first_jsonld_product(soup, expected_url=response.url, expected_title=h1_text or None)
        product_name = scraper.clean((product or {}).get("name") or h1_text)
        size_ml, size_source = scraper.extract_size_ml_from_product_page(soup, product_name)
        offer = scraper._select_product_offer(product or {}, scraper.normalise_url(response.url), product_name, size_ml)
        availability, availability_source = scraper.availability_from_product_page(soup, offer)
        price = scraper.money_to_float(offer.get("price")) if isinstance(offer, dict) else None
        if price is None:
            price, price_source = scraper.extract_price_from_html(soup)
        else:
            price_source = "sabina_jsonld"

        return {
            "diagnostic": "sabina-product-page-v3",
            "ok": True,
            "query": q,
            "input_url": url,
            "http": http,
            "scraper_module": getattr(scraper, "__file__", None),
            "result": {
                "name": product_name or None,
                "size_ml": size_ml,
                "size_source": size_source,
                "price": price,
                "price_source": price_source,
                "offer_availability": offer.get("availability") if isinstance(offer, dict) else None,
                "availability_from_product_page": availability,
                "availability_source": availability_source,
                "available_boolean": True if availability == "in_stock" else False if availability == "out_of_stock" else None,
                "jsonld_product_found": bool(product),
                "jsonld_offer_found": bool(offer),
                "html_parser_elapsed_sec": round(time.monotonic() - parse_started, 4),
            },
            "read_only": True,
            "production_search_called": False,
            "product_matcher_called": False,
            "catalog_written": False,
            "hydration_called": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }
    except requests.RequestException as exc:
        return {"diagnostic": "sabina-product-page-v3", "ok": False, "stage": "http_fetch", "query": q, "url": url, "error": f"{type(exc).__name__}: {exc}", "read_only": True}
    except Exception as exc:
        return {"diagnostic": "sabina-product-page-v3", "ok": False, "stage": "html_parse_or_availability", "query": q, "url": url, "error": f"{type(exc).__name__}: {exc}", "read_only": True}


@router.get("/diagnose-sabina-legacy-crawl")
def diagnose_sabina_legacy_crawl(
    max_pages: int = Query(1, ge=1, le=2),
    max_depth: int = Query(0, ge=0, le=1),
):
    """Preserve the existing bounded legacy-crawl diagnostic route."""
    started = time.time()
    try:
        import catalog_engine as ce
        fn = getattr(ce, "_discover_html_catalog", None)
        if fn is None:
            return {"diagnostic": "sabina-legacy-crawl-v3", "ok": False, "error": "catalog_engine._discover_html_catalog not found", "read_only": True}
        source = inspect.getsource(fn)
        old_pages = getattr(ce, "HTML_MAX_PAGES", None)
        old_depth = getattr(ce, "HTML_MAX_DEPTH", None)
        try:
            ce.HTML_MAX_PAGES = int(max_pages)
            ce.HTML_MAX_DEPTH = int(max_depth)
            result = fn("sabina", ["https://www.sabina.com/it/ricerca_old?search_query=Liquid+Brun"], time.time() + 45)
        finally:
            if old_pages is not None:
                ce.HTML_MAX_PAGES = old_pages
            if old_depth is not None:
                ce.HTML_MAX_DEPTH = old_depth
        product_urls = sorted((result.get("product_urls") or {}).keys())
        target_urls = [u for u in product_urls if "41708" in u or "34982" in u]
        return {
            "diagnostic": "sabina-legacy-crawl-v3",
            "ok": True,
            "limits": {"max_pages": max_pages, "max_depth": max_depth},
            "source_flags": {"discover_html_catalog_exists": True, "discover_calls_legacy_helper": "_sabina_legacy_product_urls" in source, "discover_has_anchor_product_extraction": "_html_product_url(store,href,page_base)" in source, "discover_has_embedded_url_extraction": "embedded_urls" in source},
            "discovery_result": {"visited": result.get("visited"), "successes": result.get("successes"), "error_count": len(result.get("errors") or []), "errors": (result.get("errors") or [])[:10], "product_url_count": len(product_urls), "target_urls": target_urls, "target_found": bool(target_urls)},
            "sample_product_urls": product_urls[:30],
            "read_only": True,
            "production_search_called": False,
            "product_matcher_called": False,
            "database_written": False,
            "catalog_resync_called": False,
            "elapsed_sec": round(time.time() - started, 3),
        }
    except Exception as exc:
        return {"diagnostic": "sabina-legacy-crawl-v3", "ok": False, "error": f"{type(exc).__name__}: {exc}", "read_only": True, "elapsed_sec": round(time.time() - started, 3)}
