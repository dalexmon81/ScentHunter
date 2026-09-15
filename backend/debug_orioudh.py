"""
Temporary diagnostic helper for Orioudh.

Purpose:
- Diagnose discovery endpoints only.
- Does NOT call ProductMatcher/family_registry.
- Does NOT modify scraper behaviour.
- Intended to be imported by a temporary main.py route.

Example:
    from debug_orioudh import diagnose_endpoints
    return diagnose_endpoints("Hawas")
"""

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, Query

router = APIRouter(
    prefix="/api/debug",
    tags=["debug"],
)

BASE_URL = "https://orioudh.com"
TIMEOUT = 8
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
}


def _request(session, method, url, params=None):
    result = {
        "url": url,
        "params": params or {},
        "ok": False,
        "status_code": None,
        "content_type": None,
        "elapsed_ms": None,
        "error": None,
        "json": None,
        "text_preview": None,
    }

    try:
        r = session.request(
            method,
            url,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        result["ok"] = r.ok
        result["status_code"] = r.status_code
        result["content_type"] = r.headers.get("content-type")
        result["elapsed_ms"] = round(r.elapsed.total_seconds() * 1000)

        if "json" in (r.headers.get("content-type") or "").lower():
            try:
                result["json"] = r.json()
            except Exception:
                result["text_preview"] = (r.text or "")[:3000]
        else:
            result["text_preview"] = (r.text or "")[:5000]

    except requests.RequestException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


def _extract_suggest_products(payload):
    products = (
        ((payload or {}).get("resources") or {})
        .get("results") or {}
    ).get("products") or []

    out = []
    for p in products:
        if not isinstance(p, dict):
            continue
        out.append({
            "title": p.get("title"),
            "vendor": p.get("vendor"),
            "url": p.get("url") or p.get("product_url"),
            "handle": p.get("handle"),
            "available": p.get("available"),
            "price": p.get("price"),
        })
    return out


def _extract_search_products(html):
    soup = BeautifulSoup(html or "", "html.parser")
    out = []
    seen = set()

    for a in soup.select('a[href*="/products/"]'):
        href = a.get("href")
        if not href:
            continue

        u = urljoin(BASE_URL, href).split("?")[0].split("#")[0].rstrip("/")
        if u in seen:
            continue
        seen.add(u)

        out.append({
            "title_attr": a.get("title"),
            "text": a.get_text(" ", strip=True)[:500],
            "url": u,
        })

    return out


def _extract_catalog_products(payload, query):
    products = (payload or {}).get("products") or []
    q = re.sub(r"[^a-z0-9]+", " ", query.lower()).split()

    out = []
    for p in products:
        if not isinstance(p, dict):
            continue

        hay = " ".join([
            str(p.get("title") or ""),
            str(p.get("vendor") or ""),
            str(p.get("handle") or ""),
        ]).lower()

        if q and all(token in hay for token in q):
            out.append({
                "title": p.get("title"),
                "vendor": p.get("vendor"),
                "handle": p.get("handle"),
                "id": p.get("id"),
                "variants": [
                    {
                        "id": v.get("id"),
                        "title": v.get("title"),
                        "available": v.get("available"),
                        "price": v.get("price"),
                        "sku": v.get("sku"),
                    }
                    for v in (p.get("variants") or [])
                    if isinstance(v, dict)
                ],
            })

    return out


def _diagnose_product_js(session, product_url):
    url = product_url.rstrip("/") + ".js"
    r = _request(session, "GET", url)

    summary = {
        "url": url,
        "ok": r["ok"],
        "status_code": r["status_code"],
        "error": r["error"],
        "product": None,
    }

    data = r.get("json")
    if isinstance(data, dict):
        summary["product"] = {
            "title": data.get("title"),
            "vendor": data.get("vendor"),
            "handle": data.get("handle"),
            "id": data.get("id"),
            "featured_image": data.get("featured_image"),
            "variants": [
                {
                    "id": v.get("id"),
                    "title": v.get("title"),
                    "available": v.get("available"),
                    "price": v.get("price"),
                    "sku": v.get("sku"),
                }
                for v in (data.get("variants") or [])
                if isinstance(v, dict)
            ],
        }

    return summary


def diagnose_endpoints(query="Hawas"):
    query = str(query or "").strip()

    result = {
        "diagnostic": True,
        "store": "Orioudh",
        "query": query,
        "note": "Temporary endpoint diagnostic. No matcher/family_registry logic is executed.",
        "endpoints": {},
    }

    if not query:
        result["error"] = "Empty query"
        return result

    with requests.Session() as session:
        # 1. Shopify predictive search
        suggest_params = {
            "q": query,
            "resources[type]": "product",
            "resources[limit]": 20,
            "resources[options][unavailable_products]": "show",
        }
        suggest = _request(
            session,
            "GET",
            BASE_URL + "/search/suggest.json",
            suggest_params,
        )
        result["endpoints"]["suggest"] = {
            **{k: suggest[k] for k in (
                "url", "params", "ok", "status_code",
                "content_type", "elapsed_ms", "error"
            )},
            "products": _extract_suggest_products(suggest.get("json")),
        }

        # 2. Normal Shopify search
        search_params = {"q": query, "type": "product"}
        search = _request(
            session,
            "GET",
            BASE_URL + "/search",
            search_params,
        )
        result["endpoints"]["search"] = {
            **{k: search[k] for k in (
                "url", "params", "ok", "status_code",
                "content_type", "elapsed_ms", "error"
            )},
            "products": _extract_search_products(search.get("text_preview", "")),
        }

        # 3. Public Shopify catalogue
        catalog = _request(
            session,
            "GET",
            BASE_URL + "/products.json",
            {"limit": 250, "page": 1},
        )
        result["endpoints"]["products_json"] = {
            **{k: catalog[k] for k in (
                "url", "params", "ok", "status_code",
                "content_type", "elapsed_ms", "error"
            )},
            "matching_products": _extract_catalog_products(
                catalog.get("json"), query
            ),
        }

        # 4. robots/sitemap discovery
        robots = _request(session, "GET", BASE_URL + "/robots.txt")
        sitemap_urls = []

        if robots.get("ok"):
            sitemap_urls = re.findall(
                r"(?im)^\s*sitemap:\s*(\S+)",
                robots.get("text_preview") or "",
            )

        result["endpoints"]["robots"] = {
            **{k: robots[k] for k in (
                "url", "params", "ok", "status_code",
                "content_type", "elapsed_ms", "error"
            )},
            "sitemaps": sitemap_urls,
        }

        # Product .js checks for candidates returned by suggest/search/catalog.
        candidate_urls = []

        for p in result["endpoints"]["suggest"]["products"]:
            u = p.get("url")
            if u:
                candidate_urls.append(urljoin(BASE_URL, u))

        for p in result["endpoints"]["search"]["products"]:
            u = p.get("url")
            if u:
                candidate_urls.append(urljoin(BASE_URL, u))

        for p in result["endpoints"]["products_json"]["matching_products"]:
            h = p.get("handle")
            if h:
                candidate_urls.append(BASE_URL + "/products/" + h)

        seen = set()
        candidate_urls = [
            u for u in candidate_urls
            if not (u in seen or seen.add(u))
        ][:20]

        result["candidate_urls"] = candidate_urls
        result["product_js"] = [
            _diagnose_product_js(session, u)
            for u in candidate_urls
        ]

    return result


@router.get("/orioudh")
def debug_orioudh(
    q: str = Query("Hawas", min_length=2),
):
    """
    Diagnostic endpoint for Orioudh discovery.

    Does not call ProductMatcher/family_registry and does not modify
    scraper behaviour.
    """
    try:
        return diagnose_endpoints(q)
    except Exception as exc:
        return {
            "diagnostic": True,
            "ok": False,
            "store": "Orioudh",
            "query": q,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="Hawas")
    args = parser.parse_args()

    print(json.dumps(
        diagnose_endpoints(args.query),
        ensure_ascii=False,
        indent=2,
    ))
