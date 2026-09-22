"""Read-only diagnostics for Sabina and Deloox.

Endpoints:
  /diagnose-sabina-liquid-brun
  /diagnose-deloox-liquid-brun

This module does not modify production scraper code. It probes the same
first-party discovery surfaces independently and reports where candidates
are lost. It intentionally uses short, bounded timeouts and parallel probes.
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, Query

router = APIRouter()

SABINA = "https://www.sabina.com"
DELOOX = "https://www.deloox.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
}
TIMEOUT = (1.5, 4.0)


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _request(url, method="get", **kwargs):
    started = time.monotonic()
    try:
        with requests.Session() as session:
            if method == "post":
                response = session.post(
                    url, headers=HEADERS, timeout=TIMEOUT, **kwargs
                )
            else:
                response = session.get(
                    url, headers=HEADERS, timeout=TIMEOUT, **kwargs
                )

            body = response.text or ""
            return {
                "ok": 200 <= response.status_code < 400,
                "status": response.status_code,
                "url": response.url,
                "elapsed_sec": round(time.monotonic() - started, 3),
                "bytes": len(body),
                "content_type": response.headers.get("content-type", ""),
                "text": body,
                "error": None,
            }
    except requests.Timeout as exc:
        return {
            "ok": False,
            "status": None,
            "url": url,
            "elapsed_sec": round(time.monotonic() - started, 3),
            "bytes": 0,
            "content_type": "",
            "text": "",
            "error": f"TIMEOUT: {exc}",
        }
    except requests.ConnectionError as exc:
        return {
            "ok": False,
            "status": None,
            "url": url,
            "elapsed_sec": round(time.monotonic() - started, 3),
            "bytes": 0,
            "content_type": "",
            "text": "",
            "error": f"CONNECTION_ERROR: {exc}",
        }
    except requests.RequestException as exc:
        return {
            "ok": False,
            "status": None,
            "url": url,
            "elapsed_sec": round(time.monotonic() - started, 3),
            "bytes": 0,
            "content_type": "",
            "text": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _compact(response):
    return {
        key: response.get(key)
        for key in (
            "ok",
            "status",
            "url",
            "elapsed_sec",
            "bytes",
            "content_type",
            "error",
        )
    }


def _sabina_product_links(html):
    soup = BeautifulSoup(html or "", "html.parser")
    urls = set()

    for anchor in soup.find_all("a", href=True):
        url = urljoin(SABINA, anchor.get("href"))
        parsed = urlparse(url)

        if parsed.netloc.lower() not in {"sabina.com", "www.sabina.com"}:
            continue

        if not parsed.path.startswith("/it/"):
            continue

        if re.search(
            r"/(?:ricerca|ricerca_old|content|marchi|negozi|contatto|faq|"
            r"carrello|ordine|module)/",
            parsed.path,
            re.I,
        ):
            continue

        urls.add(url.split("#")[0].split("?")[0])

    return sorted(urls)


def _sabina_text_hits(html, query):
    text = _clean(
        BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)
    )
    lower = text.lower()

    return {
        "query_exact_hits": lower.count(_clean(query).lower()),
        "liquid_hits": len(re.findall(r"\bliquid\b", text, re.I)),
        "brun_hits": len(re.findall(r"\bbrun\b", text, re.I)),
        "liquid_brun_hits": len(
            list(re.finditer(r"liquid\s+brun", text, re.I))
        ),
        "sample_contexts": [
            _clean(text[max(0, match.start() - 120):match.end() + 180])
            for match in list(
                re.finditer(r"liquid\s+brun", text, re.I)
            )[:5]
        ],
    }


def _sabina_current_parser(html, query):
    try:
        from scrapers.sabina.scraper import _parse_html

        rows = _parse_html(html, query)
        return {
            "parser_rows": len(rows),
            "parser_rows_sample": rows[:5],
        }
    except Exception as exc:
        return {
            "parser_rows": None,
            "parser_error": f"{type(exc).__name__}: {exc}",
        }


def _sabina_probe(endpoint, query):
    response = _request(
        endpoint["url"],
        params=endpoint.get("params"),
    )

    result = {
        "kind": endpoint["kind"],
        "method": endpoint["method"],
        "url": endpoint["url"],
        "params": endpoint.get("params"),
        "response": _compact(response),
    }

    if not response["ok"]:
        return result

    result["text_hits"] = _sabina_text_hits(response["text"], query)

    if endpoint["kind"] == "search":
        links = _sabina_product_links(response["text"])
        result["product_like_link_count"] = len(links)
        result["product_like_links_sample"] = links[:10]
        result["current_parser"] = _sabina_current_parser(
            response["text"], query
        )
    else:
        body = _clean(response["text"])
        result["body_preview"] = body[:1600]
        try:
            payload = json.loads(response["text"])
            result["json_type"] = type(payload).__name__
        except Exception:
            result["json_type"] = None

    return result


@router.get("/diagnose-sabina-liquid-brun")
def diagnose_sabina_liquid_brun(
    q: str = Query("Liquid Brun", min_length=1, max_length=120),
):
    started = time.monotonic()
    query = _clean(q)

    without_size = _clean(
        re.sub(
            r"(?<!\d)\d{2,4}\s*ml\b",
            " ",
            query,
            flags=re.I,
        )
    )

    queries = [query]
    if without_size and without_size.casefold() != query.casefold():
        queries.append(without_size)

    endpoints = []

    for search_query in queries:
        encoded = quote_plus(search_query)

        endpoints.extend(
            [
                {
                    "kind": "search",
                    "method": "GET",
                    "url": (
                        f"{SABINA}/it/ricerca"
                        f"?search_query={encoded}"
                    ),
                },
                {
                    "kind": "search",
                    "method": "GET",
                    "url": (
                        f"{SABINA}/it/ricerca_old"
                        f"?s={encoded}"
                    ),
                },
                {
                    "kind": "search",
                    "method": "GET",
                    "url": (
                        f"{SABINA}/it/ricerca_old"
                        f"?search_query={encoded}"
                    ),
                },
            ]
        )

    ajax_url = SABINA + "/modules/ecelastic/ajax.php"

    for search_query in queries:
        endpoints.extend(
            [
                {
                    "kind": "ajax",
                    "method": "GET",
                    "url": ajax_url,
                    "params": {
                        "q": search_query,
                        "query": search_query,
                        "search_query": search_query,
                        "id_lang": 5,
                        "id_country": 10,
                        "id_currency": 1,
                    },
                },
                {
                    "kind": "ajax",
                    "method": "GET",
                    "url": ajax_url,
                    "params": {
                        "s": search_query,
                        "search_query": search_query,
                        "id_lang": 5,
                        "id_country": 10,
                        "id_currency": 1,
                    },
                },
            ]
        )

    with ThreadPoolExecutor(max_workers=min(10, len(endpoints))) as pool:
        results = list(
            pool.map(
                lambda endpoint: _sabina_probe(endpoint, query),
                endpoints,
            )
        )

    status_counts = {}
    for item in results:
        status = str(item["response"].get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "diagnostic": True,
        "store": "Sabina",
        "query": query,
        "elapsed_sec": round(time.monotonic() - started, 3),
        "queries_tested": queries,
        "summary": {
            "endpoints_tested": len(results),
            "http_success": sum(
                1 for item in results if item["response"]["ok"]
            ),
            "status_counts": status_counts,
            "parser_rows_total": sum(
                (item.get("current_parser") or {}).get("parser_rows", 0)
                or 0
                for item in results
            ),
            "liquid_brun_hits_total": sum(
                item.get("text_hits", {}).get("liquid_brun_hits", 0)
                for item in results
            ),
            "transport_errors": [
                item["response"]["error"]
                for item in results
                if item["response"].get("error")
            ][:20],
        },
        "results": results,
    }


def _deloox_product_links(html):
    soup = BeautifulSoup(html or "", "html.parser")
    urls = set()

    for anchor in soup.find_all("a", href=True):
        url = (
            urljoin(DELOOX, anchor.get("href"))
            .split("#")[0]
            .split("?")[0]
        )
        parsed = urlparse(url)

        if (
            parsed.netloc.lower() in {"deloox.com", "www.deloox.com"}
            and "/product/" in parsed.path.lower()
        ):
            urls.add(url)

    for match in re.finditer(
        r'(?:https?:)?//(?:www\.)?deloox\.com/[^"\'<>\s]+/product/[^"\'<>\s]+',
        html or "",
        re.I,
    ):
        url = (
            urljoin(DELOOX, match.group(0))
            .split("#")[0]
            .split("?")[0]
        )
        if "/product/" in urlparse(url).path.lower():
            urls.add(url)

    return sorted(urls)


def _deloox_query_variants(query):
    normalized = re.sub(r"\s+", " ", query).strip()
    variants = [query]

    if normalized and normalized.casefold() != query.casefold():
        variants.append(normalized)

    meaningful = [
        token
        for token in re.findall(r"[A-Za-z0-9]+", normalized)
        if len(token) > 1
        and token.lower()
        not in {
            "for",
            "the",
            "and",
            "with",
            "in",
            "of",
            "de",
            "di",
            "da",
        }
    ]

    for token in sorted(
        set(meaningful),
        key=lambda value: (-len(value), value),
    ):
        if token.casefold() not in {
            value.casefold() for value in variants
        }:
            variants.append(token)

    return variants[:6]


def _deloox_search_probe(query):
    endpoints = []

    for search_query in _deloox_query_variants(query):
        encoded = quote_plus(search_query)

        for template in (
            f"{DELOOX}/en/search?query={encoded}",
            f"{DELOOX}/en/search?search={encoded}",
            f"{DELOOX}/en/search?q={encoded}",
            f"{DELOOX}/en?search={encoded}",
        ):
            endpoints.append(
                {
                    "query": search_query,
                    "url": template,
                }
            )

    def probe(endpoint):
        response = _request(endpoint["url"])

        item = {
            "query": endpoint["query"],
            "url": endpoint["url"],
            "response": _compact(response),
        }

        if response["ok"]:
            links = _deloox_product_links(response["text"])
            item["product_link_count"] = len(links)
            item["product_links_sample"] = links[:10]

            try:
                from scrapers.deloox.scraper import (
                    _candidate_product_urls,
                )

                candidates = _candidate_product_urls(
                    response["text"],
                    query,
                )
                item["current_scraper_candidate_count"] = len(
                    candidates
                )
                item["current_scraper_candidates_sample"] = (
                    candidates[:10]
                )
            except Exception as exc:
                item["candidate_parser_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )

        return item

    with ThreadPoolExecutor(max_workers=12) as pool:
        return list(pool.map(probe, endpoints))


def _deloox_category_probe():
    try:
        from scrapers.deloox.scraper import _category_pages

        urls = list(_category_pages())
        import_error = None
    except Exception as exc:
        urls = []
        import_error = f"{type(exc).__name__}: {exc}"

    def probe(url):
        response = _request(url)
        links = (
            _deloox_product_links(response["text"])
            if response["ok"]
            else []
        )

        return {
            "url": url,
            "response": _compact(response),
            "product_link_count": len(links),
            "product_links_sample": links[:10],
        }

    with ThreadPoolExecutor(max_workers=max(1, len(urls))) as pool:
        results = list(pool.map(probe, urls)) if urls else []

    return {
        "urls": urls,
        "import_error": import_error,
        "results": results,
    }


def _deloox_sitemap_probe():
    urls = [
        f"{DELOOX}/sitemap.xml",
        f"{DELOOX}/sitemap_index.xml",
        f"{DELOOX}/sitemap-index.xml",
        f"{DELOOX}/en/sitemap.xml",
    ]

    def probe(url):
        response = _request(url)
        locs = (
            re.findall(
                r"<loc>\s*(.*?)\s*</loc>",
                response["text"],
                re.I | re.S,
            )
            if response["ok"]
            else []
        )

        return {
            "url": url,
            "response": _compact(response),
            "loc_count": len(locs),
            "loc_sample": locs[:15],
        }

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(probe, urls))


@router.get("/diagnose-deloox-liquid-brun")
def diagnose_deloox_liquid_brun(
    q: str = Query("Liquid Brun", min_length=1, max_length=120),
):
    started = time.monotonic()
    query = _clean(q)

    search = _deloox_search_probe(query)
    categories = _deloox_category_probe()
    sitemaps = _deloox_sitemap_probe()

    return {
        "diagnostic": True,
        "store": "Deloox",
        "query": query,
        "elapsed_sec": round(time.monotonic() - started, 3),
        "summary": {
            "search_endpoints_tested": len(search),
            "search_http_success": sum(
                1
                for item in search
                if item["response"]["ok"]
            ),
            "search_product_links_total": sum(
                item.get("product_link_count", 0)
                for item in search
            ),
            "category_pages_tested": len(categories["results"]),
            "category_http_success": sum(
                1
                for item in categories["results"]
                if item["response"]["ok"]
            ),
            "category_product_links_total": sum(
                item.get("product_link_count", 0)
                for item in categories["results"]
            ),
            "sitemap_endpoints_tested": len(sitemaps),
            "sitemap_http_success": sum(
                1
                for item in sitemaps
                if item["response"]["ok"]
            ),
        },
        "search": search,
        "categories": categories,
        "sitemaps": sitemaps,
    }
