"""
ScentHunter - Sabina bounded discovery diagnostic v4.

Read-only. This module isolates Sabina native discovery routes without calling
search(), product pages, ProductMatcher, catalog, hydration, or aggregation.
It also preserves the existing product-page availability diagnostic and adds
a single-seed pagination diagnostic for the Sabina category graph.
"""

import inspect
import re
import time
from urllib.parse import urlparse, urljoin, parse_qsl, urlencode, urlunparse

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


@router.get("/diagnose-sabina-category-pagination")
def diagnose_sabina_category_pagination(
    category_url: str = Query(
        "https://www.sabina.com/it/6-profumi-di-donna",
        min_length=20,
        max_length=500,
    ),
    target: str = Query("41708", min_length=1, max_length=120),
):
    """
    Single-seed, read-only Sabina pagination diagnostic.

    Stages:
      1. Fetch exactly one category page using catalog_engine's production HTML fetch.
      2. Extract pagination-looking hrefs from the HTML.
      3. Test each candidate through catalog_engine._html_listing_url().
      4. Fetch the first accepted next-page URL only.
      5. Inspect that page for the target token and product URLs.

    No production search, matcher, hydration, catalog write, or product-page
    request is performed.
    """
    started = time.monotonic()

    base_result = {
        "diagnostic": "sabina-category-pagination-read-only-v1",
        "ok": False,
        "read_only": True,
        "production_search_called": False,
        "product_matcher_called": False,
        "hydration_called": False,
        "database_written": False,
        "category_url": category_url,
        "target": target,
    }

    try:
        import catalog_engine as ce

        fetch_fn = getattr(ce, "_fetch_html_page", None)
        listing_fn = getattr(ce, "_html_listing_url", None)
        product_fn = getattr(ce, "_html_product_url", None)
        if not callable(fetch_fn) or not callable(listing_fn) or not callable(product_fn):
            return {
                **base_result,
                "error": "required catalog_engine HTML helpers are unavailable",
                "elapsed_sec": round(time.monotonic() - started, 3),
            }

        category_started = time.monotonic()
        requested, final_url, data, error = fetch_fn("sabina", category_url)
        category_http = {
            "requested_url": requested,
            "final_url": final_url,
            "status": None if error else 200,
            "bytes": len(data or b""),
            "elapsed_sec": round(time.monotonic() - category_started, 3),
            "error": error,
        }
        if error or not data:
            return {
                **base_result,
                "stage": "category_fetch",
                "category_http": category_http,
                "elapsed_sec": round(time.monotonic() - started, 3),
            }

        page_base = final_url or category_url
        soup = BeautifulSoup(data, "html.parser")
        target_norm = str(target or "").strip().lower()
        html_lower = data.decode("utf-8", "ignore").lower()

        # Collect only links that actually look like pagination URLs. This is
        # diagnostic classification, not a production discovery rule.
        raw_candidates = []
        seen_raw = set()
        for a in soup.find_all("a", href=True):
            href = str(a.get("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(page_base, href).split("#", 1)[0]
            parsed = urlparse(absolute)
            query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
            query_keys = {str(k).lower() for k, _ in query_pairs}
            pagination_key = bool(
                query_keys.intersection({"p", "page", "pagina", "offset", "start"})
            )
            pagination_path = bool(
                re.search(r"(?:/page/|/pagina/)", parsed.path, re.I)
            )
            if not (pagination_key or pagination_path):
                continue
            if absolute in seen_raw:
                continue
            seen_raw.add(absolute)
            label = a.get_text(" ", strip=True)
            accepted = listing_fn("sabina", href, page_base, label)
            raw_candidates.append({
                "href": href,
                "absolute_url": absolute,
                "label": label[:200],
                "query_keys": sorted(query_keys),
                "accepted_by_html_listing_url": bool(accepted),
                "accepted_url": accepted,
            })

        # Also inspect embedded navigation attributes because Sabina can expose
        # pagination through data-* attributes rather than ordinary anchors.
        navigation_attrs = (
            "data-url", "data-href", "data-link", "data-next-url",
            "data-next", "data-load-more-url", "data-pagination-url",
        )
        for node in soup.find_all(True):
            for attr in navigation_attrs:
                raw = str(node.get(attr) or "").strip()
                if not raw:
                    continue
                absolute = urljoin(page_base, raw).split("#", 1)[0]
                parsed = urlparse(absolute)
                query_keys = {str(k).lower() for k, _ in parse_qsl(parsed.query, keep_blank_values=True)}
                if not (
                    query_keys.intersection({"p", "page", "pagina", "offset", "start"})
                    or re.search(r"(?:/page/|/pagina/)", parsed.path, re.I)
                ):
                    continue
                if absolute in seen_raw:
                    continue
                seen_raw.add(absolute)
                label = node.get_text(" ", strip=True)[:200]
                accepted = listing_fn("sabina", raw, page_base, label)
                raw_candidates.append({
                    "href": raw,
                    "absolute_url": absolute,
                    "label": label,
                    "query_keys": sorted(query_keys),
                    "attribute": attr,
                    "accepted_by_html_listing_url": bool(accepted),
                    "accepted_url": accepted,
                })

        accepted_urls = [
            x["accepted_url"] for x in raw_candidates
            if x.get("accepted_url")
        ]
        accepted_urls = list(dict.fromkeys(accepted_urls))

        # Prefer the first page > 1 when the retailer exposes an explicit p/page
        # parameter. Otherwise use the first accepted pagination URL.
        def page_number(url):
            try:
                params = dict(parse_qsl(urlparse(url).query, keep_blank_values=True))
                for key in ("p", "page", "pagina"):
                    if key in params and str(params[key]).isdigit():
                        return int(params[key])
            except Exception:
                pass
            return None

        ordered = sorted(
            accepted_urls,
            key=lambda u: (
                0 if (page_number(u) is not None and page_number(u) > 1) else 1,
                page_number(u) if page_number(u) is not None else 999999,
                u,
            ),
        )
        next_url = ordered[0] if ordered else None

        pagination_summary = {
            "raw_pagination_candidates": len(raw_candidates),
            "accepted_pagination_urls": len(accepted_urls),
            "accepted_urls_sample": accepted_urls[:30],
            "selected_next_url": next_url,
            "selected_page_number": page_number(next_url) if next_url else None,
        }

        result = {
            **base_result,
            "ok": True,
            "stage": "category_parsed",
            "category_http": category_http,
            "pagination": pagination_summary,
            "pagination_candidates": raw_candidates[:100],
            "category_target_text_hit": target_norm in html_lower if target_norm else False,
        }

        if not next_url:
            result["stage"] = "pagination_not_found_or_rejected"
            result["diagnosis"] = (
                "CATEGORY_FETCH_OK_BUT_NO_ACCEPTED_PAGINATION: the category page "
                "was fetched, but no pagination URL was both discovered and accepted "
                "by _html_listing_url()."
            )
            result["elapsed_sec"] = round(time.monotonic() - started, 3)
            return result

        next_started = time.monotonic()
        req2, final2, data2, error2 = fetch_fn("sabina", next_url)
        next_http = {
            "requested_url": req2,
            "final_url": final2,
            "status": None if error2 else 200,
            "bytes": len(data2 or b""),
            "elapsed_sec": round(time.monotonic() - next_started, 3),
            "error": error2,
        }
        result["next_page_http"] = next_http

        if error2 or not data2:
            result["stage"] = "next_page_fetch_failed"
            result["diagnosis"] = (
                "PAGINATION_ACCEPTED_BUT_NEXT_PAGE_FETCH_FAILED: the pagination "
                "URL is accepted by _html_listing_url(), but the production HTML "
                "fetch could not retrieve it."
            )
            result["elapsed_sec"] = round(time.monotonic() - started, 3)
            return result

        soup2 = BeautifulSoup(data2, "html.parser")
        text2 = soup2.get_text(" ", strip=True)
        lower2 = data2.decode("utf-8", "ignore").lower()

        product_urls = []
        for a in soup2.find_all("a", href=True):
            product = product_fn("sabina", a.get("href"), final2 or next_url)
            if product:
                product_urls.append(product)

        for item in getattr(ce, "_jsonld", lambda _s: [])(soup2):
            product = product_fn("sabina", item.get("url"), final2 or next_url)
            if product:
                product_urls.append(product)

        product_urls = list(dict.fromkeys(product_urls))
        target_urls = [
            u for u in product_urls
            if target_norm and target_norm in u.lower()
        ]

        # This helper is generic and read-only; it does not fetch product pages.
        legacy_urls = []
        legacy_fn = getattr(ce, "_sabina_legacy_product_urls", None)
        if callable(legacy_fn):
            try:
                legacy_urls = list(legacy_fn(data2, final2 or next_url))
            except Exception as exc:
                result["legacy_helper_error"] = f"{type(exc).__name__}: {exc}"

        legacy_target_urls = [
            u for u in legacy_urls
            if target_norm and target_norm in u.lower()
        ]

        result.update({
            "stage": "next_page_parsed",
            "next_page": {
                "bytes": len(data2),
                "target_text_hit": target_norm in lower2 if target_norm else False,
                "target_url_hit": bool(target_urls),
                "target_urls": target_urls[:20],
                "product_url_count": len(product_urls),
                "product_urls_sample": product_urls[:50],
                "legacy_product_url_count": len(legacy_urls),
                "legacy_target_urls": legacy_target_urls[:20],
                "liquid_brun_text_hit": "liquid brun" in lower2,
                "french_avenue_text_hit": "french avenue" in lower2,
            },
            "diagnosis": (
                "TARGET_REACHED_ON_NEXT_PAGE"
                if target_urls or legacy_target_urls or (target_norm and target_norm in lower2)
                else
                "NEXT_PAGE_FETCHED_TARGET_NOT_PRESENT: pagination works for the first "
                "next page, but the requested target is not on that page."
            ),
            "elapsed_sec": round(time.monotonic() - started, 3),
        })
        return result

    except Exception as exc:
        return {
            **base_result,
            "stage": "exception",
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_sec": round(time.monotonic() - started, 3),
        }


@router.get("/diagnose-sabina-category-pages")
def diagnose_sabina_category_pages(
    category_url: str = Query(
        "https://www.sabina.com/it/6-profumi-di-donna",
        min_length=20,
        max_length=500,
    ),
    pages: str = Query("2,3,42", min_length=1, max_length=120),
    target: str = Query("41708", min_length=1, max_length=120),
):
    """
    Read-only probe of explicitly selected Sabina category pages.

    This intentionally does not use the crawler frontier. It fetches only the
    requested p=N pages through the production HTML fetch helper, then reports
    whether the target occurs in page text, product URLs, JSON-LD, or the
    generic Sabina legacy-ID extraction.
    """
    started = time.monotonic()
    base_result = {
        "diagnostic": "sabina-category-pages-read-only-v1",
        "ok": False,
        "read_only": True,
        "production_search_called": False,
        "product_matcher_called": False,
        "hydration_called": False,
        "database_written": False,
        "category_url": category_url,
        "target": target,
    }

    try:
        import catalog_engine as ce

        fetch_fn = getattr(ce, "_fetch_html_page", None)
        listing_fn = getattr(ce, "_html_listing_url", None)
        product_fn = getattr(ce, "_html_product_url", None)
        if not callable(fetch_fn) or not callable(listing_fn) or not callable(product_fn):
            return {
                **base_result,
                "error": "required catalog_engine HTML helpers are unavailable",
                "elapsed_sec": round(time.monotonic() - started, 3),
            }

        requested_pages = []
        for raw in str(pages or "").split(","):
            raw = raw.strip()
            if raw.isdigit():
                n = int(raw)
                if 1 <= n <= 1000 and n not in requested_pages:
                    requested_pages.append(n)

        if not requested_pages:
            return {
                **base_result,
                "error": "no_valid_pages",
                "elapsed_sec": round(time.monotonic() - started, 3),
            }

        target_norm = str(target or "").strip().lower()
        results = []

        for page_number in requested_pages:
            if page_number == 1:
                url = category_url
            else:
                parsed = urlparse(category_url)
                pairs = [
                    (k, v) for k, v in parse_qsl(
                        parsed.query, keep_blank_values=True
                    )
                    if k.lower() != "p"
                ]
                pairs.append(("p", str(page_number)))
                url = urlunparse(
                    (
                        parsed.scheme,
                        parsed.netloc,
                        parsed.path,
                        parsed.params,
                        urlencode(pairs),
                        parsed.fragment,
                    )
                )

            page_started = time.monotonic()
            requested, final_url, data, error = fetch_fn("sabina", url)
            item = {
                "page": page_number,
                "requested_url": requested,
                "final_url": final_url,
                "status": None if error else 200,
                "bytes": len(data or b""),
                "elapsed_sec": round(time.monotonic() - page_started, 3),
                "error": error,
            }

            if error or not data:
                item["diagnosis"] = "FETCH_FAILED"
                results.append(item)
                continue

            soup = BeautifulSoup(data, "html.parser")
            lower = data.decode("utf-8", "ignore").lower()
            text = soup.get_text(" ", strip=True).lower()

            product_urls = []
            for a in soup.find_all("a", href=True):
                product = product_fn(
                    "sabina",
                    a.get("href"),
                    final_url or url,
                )
                if product:
                    product_urls.append(product)

            for ld in getattr(ce, "_jsonld", lambda _s: [])(soup):
                product = product_fn(
                    "sabina",
                    ld.get("url"),
                    final_url or url,
                )
                if product:
                    product_urls.append(product)

            product_urls = list(dict.fromkeys(product_urls))
            target_urls = [
                u for u in product_urls
                if target_norm and target_norm in u.lower()
            ]

            legacy_urls = []
            legacy_fn = getattr(ce, "_sabina_legacy_product_urls", None)
            if callable(legacy_fn):
                try:
                    legacy_urls = list(
                        legacy_fn(data, final_url or url)
                    )
                except Exception as exc:
                    item["legacy_helper_error"] = (
                        f"{type(exc).__name__}: {exc}"
                    )

            legacy_target_urls = [
                u for u in legacy_urls
                if target_norm and target_norm in u.lower()
            ]

            item.update({
                "target_text_hit": bool(target_norm and target_norm in text),
                "target_raw_html_hit": bool(target_norm and target_norm in lower),
                "target_url_hit": bool(target_urls),
                "target_urls": target_urls[:20],
                "product_url_count": len(product_urls),
                "product_urls_sample": product_urls[:40],
                "legacy_product_url_count": len(legacy_urls),
                "legacy_target_urls": legacy_target_urls[:20],
                "liquid_brun_text_hit": "liquid brun" in text,
                "french_avenue_text_hit": "french avenue" in text,
                "pagination_links": [
                    href for href in (
                        urljoin(final_url or url, a.get("href"))
                        for a in soup.find_all("a", href=True)
                    )
                    if href and re.search(
                        r"(?:[?&](?:p|page|pagina)=\d+|/page/\d+|/pagina/\d+)",
                        href,
                        re.I,
                    )
                ][:30],
            })

            item["diagnosis"] = (
                "TARGET_FOUND"
                if (
                    item["target_text_hit"]
                    or item["target_raw_html_hit"]
                    or item["target_url_hit"]
                    or legacy_target_urls
                )
                else "TARGET_NOT_ON_PAGE"
            )
            results.append(item)

        found_pages = [
            r["page"] for r in results if r.get("diagnosis") == "TARGET_FOUND"
        ]

        return {
            **base_result,
            "ok": True,
            "requested_pages": requested_pages,
            "results": results,
            "target_found_on_pages": found_pages,
            "diagnosis": (
                "TARGET_FOUND_ON_SELECTED_PAGE"
                if found_pages
                else "TARGET_NOT_FOUND_ON_SELECTED_PAGES"
            ),
            "elapsed_sec": round(time.monotonic() - started, 3),
        }

    except Exception as exc:
        return {
            **base_result,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_sec": round(time.monotonic() - started, 3),
        }


@router.get("/diagnose-sabina-category-pages-batch")
def diagnose_sabina_category_pages_batch(
    category_url: str = Query(
        "https://www.sabina.com/it/6-profumi-di-donna",
        min_length=20,
        max_length=500,
    ),
    start_page: int = Query(1, ge=1, le=1000),
    end_page: int = Query(42, ge=1, le=1000),
    workers: int = Query(8, ge=1, le=12),
    target: str = Query("41708", min_length=1, max_length=120),
):
    """
    Read-only parallel probe of a bounded Sabina category page interval.

    It deliberately bypasses the generic discovery frontier. Each requested
    p=N URL is fetched through catalog_engine._fetch_html_page, then inspected
    only for the target and product links. No DB, matcher, hydration, search,
    or product-page fetch is performed.
    """
    started = time.monotonic()
    base_result = {
        "diagnostic": "sabina-category-pages-batch-read-only-v1",
        "ok": False,
        "read_only": True,
        "production_search_called": False,
        "product_matcher_called": False,
        "hydration_called": False,
        "database_written": False,
        "category_url": category_url,
        "target": target,
    }

    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import catalog_engine as ce

        fetch_fn = getattr(ce, "_fetch_html_page", None)
        product_fn = getattr(ce, "_html_product_url", None)
        if not callable(fetch_fn) or not callable(product_fn):
            return {
                **base_result,
                "error": "required catalog_engine HTML helpers are unavailable",
                "elapsed_sec": round(time.monotonic() - started, 3),
            }

        if end_page < start_page:
            return {
                **base_result,
                "error": "end_page_must_be_greater_or_equal_to_start_page",
                "elapsed_sec": round(time.monotonic() - started, 3),
            }

        page_numbers = list(range(start_page, end_page + 1))
        if len(page_numbers) > 100:
            return {
                **base_result,
                "error": "maximum_batch_span_is_100_pages",
                "elapsed_sec": round(time.monotonic() - started, 3),
            }

        target_norm = str(target or "").strip().lower()

        def make_url(n):
            parsed = urlparse(category_url)
            pairs = [
                (k, v) for k, v in parse_qsl(
                    parsed.query, keep_blank_values=True
                )
                if k.lower() != "p"
            ]
            if n != 1:
                pairs.append(("p", str(n)))
            return urlunparse(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    parsed.params,
                    urlencode(pairs),
                    parsed.fragment,
                )
            )

        def probe(n):
            url = make_url(n)
            page_started = time.monotonic()
            requested, final_url, data, error = fetch_fn("sabina", url)

            item = {
                "page": n,
                "requested_url": requested,
                "final_url": final_url,
                "status": None if error else 200,
                "bytes": len(data or b""),
                "elapsed_sec": round(time.monotonic() - page_started, 3),
                "error": error,
            }

            if error or not data:
                item["diagnosis"] = "FETCH_FAILED"
                return item

            soup = BeautifulSoup(data, "html.parser")
            text = soup.get_text(" ", strip=True).lower()
            raw = data.decode("utf-8", "ignore").lower()

            product_urls = []
            for a in soup.find_all("a", href=True):
                product = product_fn("sabina", a.get("href"), final_url or url)
                if product:
                    product_urls.append(product)

            for ld in getattr(ce, "_jsonld", lambda _s: [])(soup):
                product = product_fn("sabina", ld.get("url"), final_url or url)
                if product:
                    product_urls.append(product)

            product_urls = list(dict.fromkeys(product_urls))
            target_urls = [
                u for u in product_urls
                if target_norm and target_norm in u.lower()
            ]

            item.update({
                "target_text_hit": bool(target_norm and target_norm in text),
                "target_raw_html_hit": bool(target_norm and target_norm in raw),
                "target_url_hit": bool(target_urls),
                "target_urls": target_urls[:10],
                "product_url_count": len(product_urls),
                "product_urls_sample": product_urls[:10],
                "liquid_brun_text_hit": "liquid brun" in text,
                "french_avenue_text_hit": "french avenue" in text,
                "diagnosis": (
                    "TARGET_FOUND"
                    if (
                        target_urls
                        or (target_norm and target_norm in text)
                        or (target_norm and target_norm in raw)
                    )
                    else "TARGET_NOT_ON_PAGE"
                ),
            })
            return item

        results = []
        with ThreadPoolExecutor(max_workers=min(int(workers), len(page_numbers))) as pool:
            futures = {
                pool.submit(probe, n): n for n in page_numbers
            }
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    n = futures[future]
                    results.append({
                        "page": n,
                        "diagnosis": "EXCEPTION",
                        "error": f"{type(exc).__name__}: {exc}",
                    })

        results.sort(key=lambda x: x.get("page", 0))
        found = [
            r for r in results if r.get("diagnosis") == "TARGET_FOUND"
        ]
        failures = [
            r for r in results if r.get("diagnosis") == "FETCH_FAILED"
        ]

        return {
            **base_result,
            "ok": True,
            "parameters": {
                "start_page": start_page,
                "end_page": end_page,
                "page_count": len(page_numbers),
                "workers": workers,
            },
            "results": results,
            "target_found_on_pages": [
                r.get("page") for r in found
            ],
            "fetch_failures": [
                {"page": r.get("page"), "error": r.get("error")}
                for r in failures
            ],
            "pages_with_liquid_brun_text": [
                r.get("page") for r in results
                if r.get("liquid_brun_text_hit")
            ],
            "pages_with_french_avenue_text": [
                r.get("page") for r in results
                if r.get("french_avenue_text_hit")
            ],
            "diagnosis": (
                "TARGET_FOUND_IN_CATEGORY_INTERVAL"
                if found
                else "TARGET_NOT_FOUND_IN_CATEGORY_INTERVAL"
            ),
            "elapsed_sec": round(time.monotonic() - started, 3),
        }

    except Exception as exc:
        return {
            **base_result,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_sec": round(time.monotonic() - started, 3),
        }
