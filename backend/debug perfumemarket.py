from __future__ import annotations

import json
import re
import traceback
from urllib.parse import quote, urljoin, urlparse
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/debug", tags=["debug"])

BASE_URL = "https://www.perfumemarket.nl"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.8",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
}

TIMEOUT = (3.0, 10.0)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_url(url):
    value = urljoin(BASE_URL, clean(url))
    parsed = urlparse(value)

    if parsed.scheme not in ("http", "https"):
        return ""

    if parsed.netloc and "perfumemarket" not in parsed.netloc.lower():
        return ""

    return value.split("?", 1)[0].rstrip("/")


def request(session, url):
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        return {
            "ok": True,
            "status_code": response.status_code,
            "final_url": response.url,
            "text": response.text or "",
            "content_type": response.headers.get("content-type", ""),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def term_hits(text, terms):
    lower = (text or "").lower()
    hits = []

    for term in terms:
        if term.lower() in lower:
            hits.append(term)

    return hits


def extract_product_links(html, terms):
    soup = BeautifulSoup(html or "", "html.parser")

    products = []
    seen = set()

    for a in soup.find_all("a", href=True):
        raw_href = str(a.get("href") or "")
        href = normalize_url(raw_href)

        if not href or "/products/" not in href.lower():
            continue

        if href.lower() in seen:
            continue

        seen.add(href.lower())

        text = clean(a.get_text(" ", strip=True))

        node = a
        context = text

        for _ in range(8):
            node = getattr(node, "parent", None)
            if node is None:
                break

            candidate = clean(node.get_text(" ", strip=True))

            if len(candidate) <= 1800 and len(candidate) > len(context):
                context = candidate

            if len(context) > 1200:
                break

        blob = f"{text} {context} {href}"

        if not term_hits(blob, terms):
            continue

        products.append(
            {
                "url": href,
                "text": text[:500],
                "context": context[:1800],
                "hits": term_hits(blob, terms),
            }
        )

    return products


def parse_sitemap_locs(xml_text):
    try:
        root = ET.fromstring(xml_text or "")
    except Exception:
        return []

    locs = []

    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1].lower()

        if tag == "loc" and element.text:
            locs.append(clean(element.text))

    return locs


def inspect_sitemap(session, sitemap_url, terms):
    result = {
        "requested": sitemap_url,
        "status_code": None,
        "final_url": None,
        "error": None,
        "loc_count": 0,
        "child_sitemaps": [],
        "matching_urls": [],
    }

    response = request(session, sitemap_url)

    if not response["ok"]:
        result["error"] = {
            "type": response["error_type"],
            "message": response["error"],
        }
        return result

    result["status_code"] = response["status_code"]
    result["final_url"] = response["final_url"]

    locs = parse_sitemap_locs(response["text"])
    result["loc_count"] = len(locs)

    lower_text = response["text"].lower()

    # Sitemap index.
    if "<sitemapindex" in lower_text:
        result["child_sitemaps"] = [
            url
            for url in locs
            if "sitemap" in url.lower()
        ][:100]

        matching = []

        for child in result["child_sitemaps"]:
            child_response = request(session, child)

            if not child_response["ok"]:
                matching.append(
                    {
                        "sitemap": child,
                        "error": child_response["error"],
                    }
                )
                continue

            child_locs = parse_sitemap_locs(child_response["text"])

            for loc in child_locs:
                if any(
                    term.lower() in loc.lower()
                    for term in terms
                ):
                    matching.append(
                        {
                            "sitemap": child,
                            "url": loc,
                            "hits": term_hits(loc, terms),
                        }
                    )

        result["matching_urls"] = matching[:200]
        return result

    result["matching_urls"] = [
        {
            "url": loc,
            "hits": term_hits(loc, terms),
        }
        for loc in locs
        if any(term.lower() in loc.lower() for term in terms)
    ][:200]

    return result


@router.get("/perfumemarket")
def debug_perfumemarket(
    q: str = Query(..., min_length=2),
):
    """
    DIAGNOSTIC ONLY.

    This endpoint does NOT modify the PerfumeMarket scraper.

    It traces:
    1. Shopify predictive search.
    2. Shopify normal search variants.
    3. The public sitemap/index and product sitemap URLs.
    4. The two collections currently known to contain the missing products.
    5. The actual scraper discovery() result.

    The goal is to identify exactly where Hawas Black / Hawas Diva
    disappear from the discovery pipeline.
    """
    query = str(q or "").strip()

    # These are diagnostic targets only. They do not alter production
    # matching or discovery behavior.
    focus_terms = [
        query,
        "Hawas Black",
        "Hawas Diva",
        "Hawas Eclat",
        "Hawas Women Eclat",
    ]

    # Remove duplicates while preserving order.
    unique_terms = []
    seen_terms = set()

    for term in focus_terms:
        key = term.lower()
        if key in seen_terms:
            continue
        seen_terms.add(key)
        unique_terms.append(term)

    encoded = quote(query)

    endpoints = [
        (
            "predictive",
            (
                f"{BASE_URL}/search/suggest.json"
                f"?q={encoded}"
                "&resources[type]=product"
                "&resources[limit]=20"
                "&resources[options][unavailable_products]=last"
            ),
        ),
        (
            "search_type_product_prefix_last",
            (
                f"{BASE_URL}/search?q={encoded}"
                "&type=product"
                "&options%5Bprefix%5D=last"
                "&options%5Bunavailable_products%5D=last"
            ),
        ),
        (
            "search_type_product",
            f"{BASE_URL}/search?q={encoded}&type=product",
        ),
        (
            "search_plain",
            f"{BASE_URL}/search?q={encoded}",
        ),
    ]

    # These are public collection pages confirmed to contain the relevant
    # PerfumeMarket products. They are inspected only diagnostically.
    collection_endpoints = [
        (
            "oriental_woody",
            f"{BASE_URL}/collections/oriental-woody",
        ),
        (
            "women_perfumes",
            f"{BASE_URL}/collections/women-perfumes",
        ),
    ]

    pages = []

    session = requests.Session()

    try:
        # ---------------------------------------------------------------
        # 1. Actual search endpoints used by the production scraper.
        # ---------------------------------------------------------------
        for label, endpoint in endpoints:
            response = request(session, endpoint)

            page = {
                "type": "search_endpoint",
                "label": label,
                "requested": endpoint,
                "status_code": response.get("status_code"),
                "final_url": response.get("final_url"),
                "content_type": response.get("content_type"),
                "html_length": len(response.get("text") or ""),
                "focus_hits_in_raw_response": term_hits(
                    response.get("text") or "",
                    unique_terms,
                ),
                "product_links": [],
                "error": response.get("error"),
            }

            if response.get("ok"):
                html = response.get("text") or ""

                if "json" in (response.get("content_type") or "").lower():
                    # Predictive endpoint: preserve useful raw matches but
                    # also inspect any product URLs exposed in the JSON.
                    product_urls = sorted(
                        set(
                            re.findall(
                                r'https?://[^"\\\s]+/products/[^"\\\s]+',
                                html,
                                flags=re.I,
                            )
                        )
                    )

                    page["product_urls"] = [
                        {
                            "url": normalize_url(url),
                            "hits": term_hits(url, unique_terms),
                        }
                        for url in product_urls
                        if any(
                            term.lower() in url.lower()
                            for term in unique_terms
                        )
                    ][:200]

                page["product_links"] = extract_product_links(
                    html,
                    unique_terms,
                )[:200]

            pages.append(page)

        # ---------------------------------------------------------------
        # 2. Direct collection pages.
        # ---------------------------------------------------------------
        for label, endpoint in collection_endpoints:
            response = request(session, endpoint)

            page = {
                "type": "collection",
                "label": label,
                "requested": endpoint,
                "status_code": response.get("status_code"),
                "final_url": response.get("final_url"),
                "content_type": response.get("content_type"),
                "html_length": len(response.get("text") or ""),
                "focus_hits_in_raw_response": term_hits(
                    response.get("text") or "",
                    unique_terms,
                ),
                "product_links": [],
                "error": response.get("error"),
            }

            if response.get("ok"):
                page["product_links"] = extract_product_links(
                    response.get("text") or "",
                    unique_terms,
                )[:200]

            pages.append(page)

        # ---------------------------------------------------------------
        # 3. Public sitemap / product sitemap.
        # ---------------------------------------------------------------
        sitemap_candidates = [
            f"{BASE_URL}/sitemap.xml",
            f"{BASE_URL}/sitemap_products_1.xml",
        ]

        sitemap_results = []

        for sitemap_url in sitemap_candidates:
            sitemap_results.append(
                inspect_sitemap(
                    session,
                    sitemap_url,
                    unique_terms,
                )
            )

        # If sitemap.xml exposes additional product sitemaps, inspect
        # those too, but cap the total to keep this diagnostic bounded.
        sitemap_index = sitemap_results[0]

        for child in sitemap_index.get("child_sitemaps", [])[:20]:
            if child in sitemap_candidates:
                continue

            sitemap_results.append(
                inspect_sitemap(
                    session,
                    child,
                    unique_terms,
                )
            )

        # ---------------------------------------------------------------
        # 4. Inspect matching product URLs from sitemap/collections.
        # ---------------------------------------------------------------
        candidate_urls = []
        seen_urls = set()

        for sitemap in sitemap_results:
            for item in sitemap.get("matching_urls", []):
                url = normalize_url(item.get("url"))

                if not url or "/products/" not in url.lower():
                    continue

                key = url.lower()

                if key in seen_urls:
                    continue

                seen_urls.add(key)
                candidate_urls.append(url)

        for page in pages:
            for item in page.get("product_links", []):
                url = normalize_url(item.get("url"))

                if not url or "/products/" not in url.lower():
                    continue

                key = url.lower()

                if key in seen_urls:
                    continue

                seen_urls.add(key)
                candidate_urls.append(url)

        product_inspections = []

        for product_url in candidate_urls[:50]:
            response = request(
                session,
                product_url + ".js",
            )

            entry = {
                "product_url": product_url,
                "status_code": response.get("status_code"),
                "final_url": response.get("final_url"),
                "content_type": response.get("content_type"),
                "error": response.get("error"),
            }

            if response.get("ok"):
                text = response.get("text") or ""

                try:
                    payload = json.loads(text)

                    if isinstance(payload, dict):
                        entry["title"] = payload.get("title")
                        entry["vendor"] = payload.get("vendor")
                        entry["handle"] = payload.get("handle")
                        entry["available"] = payload.get("available")

                        variants = payload.get("variants") or []

                        if isinstance(variants, list):
                            entry["variant_count"] = len(variants)
                            entry["variants"] = [
                                {
                                    "id": variant.get("id"),
                                    "title": variant.get("title"),
                                    "available": variant.get("available"),
                                    "price": variant.get("price"),
                                }
                                for variant in variants[:30]
                                if isinstance(variant, dict)
                            ]
                except Exception:
                    entry["raw_prefix"] = text[:1500]

            product_inspections.append(entry)

        # ---------------------------------------------------------------
        # 5. Run the ACTUAL PerfumeMarket discovery() function.
        # ---------------------------------------------------------------
        actual_discovery = {
            "error": None,
            "candidate_count": None,
            "candidates": [],
        }

        try:
            from scrapers.perfumemarket.scraper import discover

            candidates = discover(
                session,
                query,
            )

            actual_discovery["candidate_count"] = len(candidates)
            actual_discovery["candidates"] = candidates[:100]

        except Exception as exc:
            actual_discovery["error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }

        return {
            "diagnostic": True,
            "ok": True,
            "store": "PerfumeMarket",
            "query": query,
            "focus_terms": unique_terms,
            "pages": pages,
            "sitemaps": sitemap_results,
            "product_inspections": product_inspections,
            "actual_discovery": actual_discovery,
        }

    except Exception as exc:
        return {
            "diagnostic": True,
            "ok": False,
            "store": "PerfumeMarket",
            "query": query,
            "stage": "debug_perfumemarket",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }

    finally:
        session.close()
