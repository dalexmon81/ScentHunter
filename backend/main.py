"""
ScentHunter API entrypoint.

This entrypoint keeps the existing main_legacy application and SearchEngine,
while exposing read-only Notino diagnostics useful for debugging the retailer
adapter without changing the frontend or the other stores.
"""

from __future__ import annotations

import importlib
import json
import re
from typing import Any, Dict, List
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from fastapi import Query

import main_legacy as _legacy
from main_legacy import *
from search_engine import SearchEngine


_engine = SearchEngine(_legacy)

# The FastAPI route functions live in main_legacy.py and resolve globals from
# that module namespace. Patch those names there, not only in this wrapper.
_legacy.search_perfume = _engine.search
_legacy._run_search_job = _engine.run_job
_legacy._validate_candidate = _legacy._validate_candidate
_legacy._validate_candidates_parallel = _legacy._validate_candidates_parallel
app = _legacy.app


# ============================================================
# NOTINO DEEP DIAGNOSTIC
# ============================================================

JINA_PREFIX = "https://r.jina.ai/"
NOTINO_BASE = "https://www.notino.fr"


def _snippet(text: str, needle: str, radius: int = 220) -> Dict[str, Any]:
    low = text.casefold()
    pos = low.find(needle.casefold())
    if pos < 0:
        return {"found": False, "needle": needle}
    start = max(0, pos - radius)
    end = min(len(text), pos + len(needle) + radius)
    return {
        "found": True,
        "needle": needle,
        "position": pos,
        "context": text[start:end],
    }


def _probe_html(html: str, query: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html or "", "html.parser")
    hrefs: List[Dict[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if href:
            hrefs.append({
                "href": href,
                "text": anchor.get_text(" ", strip=True)[:300],
            })

    product_href_re = re.compile(r"/p-\d+/?(?:[?#].*)?$", re.I)
    product_hrefs = [
        item for item in hrefs
        if product_href_re.search(item["href"].split("#", 1)[0])
    ]

    raw_product_urls = sorted(set(re.findall(
        r"https?://(?:www\.)?notino\.fr/[^\"'<>\\s]+?/p-\d+/?",
        html or "",
        re.I,
    )))

    relative_product_urls = sorted(set(re.findall(
        r"(?:(?:href|url|canonical|productUrl|product_url)[\\\"'=: ]+)?"
        r"(?:/(?:[a-z0-9][^\"'<>\\s]*/)+p-\d+/?|"
        r"https?://(?:www\.)?notino\.fr/[^\"'<>\\s]+?/p-\d+/? )",
        (html or "").replace(" ", " "),
        re.I,
    )))

    # Prefer the actual scraper's URL detection as the authoritative count.
    scraper_products: List[Dict[str, Any]] = []
    scraper_error = None
    try:
        module = importlib.import_module("scrapers.notino.scraper")
        extractor = getattr(module, "extract_candidates_from_html", None)
        if callable(extractor):
            try:
                extracted = extractor(html or "", query)
                scraper_products = list(extracted or [])[:30]
            except Exception as exc:
                scraper_error = f"{type(exc).__name__}: {exc}"
        else:
            scraper_error = "extract_candidates_from_html missing"
    except Exception as exc:
        scraper_error = f"module_load: {type(exc).__name__}: {exc}"

    jsonld_products: List[Dict[str, Any]] = []
    for script in soup.find_all("script", type=re.compile(r"ld\+json", re.I)):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        queue: List[Any] = data if isinstance(data, list) else [data]
        while queue:
            item = queue.pop(0)
            if isinstance(item, list):
                queue.extend(item)
                continue
            if not isinstance(item, dict):
                continue

            item_type = item.get("@type")
            if item_type == "Product" or (
                isinstance(item_type, list) and "Product" in item_type
            ):
                jsonld_products.append({
                    "name": item.get("name"),
                    "brand": item.get("brand"),
                    "sku": item.get("sku"),
                    "gtin": item.get("gtin13") or item.get("gtin"),
                    "url": item.get("url"),
                })

            for value in item.values():
                if isinstance(value, (dict, list)):
                    queue.append(value)

    text = soup.get_text(" ", strip=True)
    needles = [
        query,
        "9 PM",
        "Afnan",
        "AFN00282",
        "16167394",
        "100 ml",
        "36,00",
        "/p-",
    ]

    return {
        "html_length": len(html or ""),
        "text_length": len(text),
        "href_count": len(hrefs),
        "product_href_count": len(product_hrefs),
        "product_hrefs": product_hrefs[:50],
        "raw_product_url_count": len(raw_product_urls),
        "raw_product_urls": raw_product_urls[:50],
        "relative_product_url_count": len(relative_product_urls),
        "relative_product_urls": relative_product_urls[:50],
        "jsonld_product_count": len(jsonld_products),
        "jsonld_products": jsonld_products[:50],
        "scraper_extractor_count": len(scraper_products),
        "scraper_extractor_items": scraper_products,
        "scraper_extractor_error": scraper_error,
        "needles": [_snippet(html or "", needle) for needle in needles],
        "text_needles": [_snippet(text, needle) for needle in needles],
    }


@app.get("/diagnose-notino-deep")
def diagnose_notino_deep(q: str = Query(..., min_length=1)):
    query = str(q or "").strip()
    discovery_queries = [query]
    tokens = re.findall(r"[a-z0-9]+", query.lower())
    generic = {
        "pour", "femme", "femmes", "for", "woman", "women",
        "men", "homme", "hommes", "unisex", "unisexe",
        "eau", "de", "parfum", "parfums", "edp", "edt",
    }
    meaningful = [token for token in tokens if token not in generic]
    if len(meaningful) >= 2:
        identity = " ".join(meaningful)
        if identity.casefold() != query.casefold():
            discovery_queries.append(identity)

    urls: List[str] = []
    for discovery_query in discovery_queries[:2]:
        encoded = quote_plus(discovery_query)
        urls.extend([
            f"{NOTINO_BASE}/search.asp?exps={encoded}",
            f"{NOTINO_BASE}/search?query={encoded}",
        ])

    reports: List[Dict[str, Any]] = []
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/131 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    })

    for source_url in urls:
        reader_url = JINA_PREFIX + source_url
        report: Dict[str, Any] = {
            "source_url": source_url,
            "reader_url": reader_url,
        }
        try:
            response = session.get(reader_url, timeout=30, allow_redirects=True)
            report.update({
                "status": response.status_code,
                "final_url": response.url,
                "content_type": response.headers.get("content-type"),
                "bytes": len(response.content),
            })
            if response.ok:
                report["probe"] = _probe_html(response.text, query)
        except Exception as exc:
            report["error"] = f"{type(exc).__name__}: {exc}"
        reports.append(report)

    session.close()
    return {
        "ok": True,
        "diagnostic": "notino-deep-read-only-v2",
        "query": query,
        "discovery_queries": discovery_queries[:2],
        "reports": reports,
    }


@app.get("/diagnose-notino-live")
def diagnose_notino_live(q: str = Query(..., min_length=1)):
    """Run the Notino adapter's own diagnostics plus a compatibility contract check."""
    query = str(q or "").strip()
    module = importlib.import_module("scrapers.notino.scraper")

    diagnostic_fn = getattr(module, "diagnose", None)
    search_fn = getattr(module, "search", None)

    contract = {
        "scraper_version": getattr(module, "SCRAPER_VERSION", "unknown"),
        "BASE_URL": getattr(module, "BASE_URL", None),
        "BASEURL_defined": "BASEURL" in vars(module),
        "displayname_callable": callable(getattr(module, "displayname", None)),
        "_result_callable": callable(getattr(module, "_result", None)),
        "extract_candidates_from_html_callable": callable(getattr(module, "extract_candidates_from_html", None)),
        "search_callable": callable(search_fn),
        "diagnose_callable": callable(diagnostic_fn),
    }

    diagnostic = diagnostic_fn(query) if callable(diagnostic_fn) else {"error": "diagnose() missing"}

    search_result: Dict[str, Any]
    if callable(search_fn):
        try:
            results = search_fn(query)
            search_result = {
                "ok": True,
                "count": len(results or []),
                "results": (results or [])[:30],
            }
        except Exception as exc:
            search_result = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
    else:
        search_result = {"ok": False, "error": "search() missing"}

    return {
        "ok": bool(search_result.get("ok")),
        "query": query,
        "contract": contract,
        "diagnostic": diagnostic,
        "search": search_result,
    }
