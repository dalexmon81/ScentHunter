"""
ScentHunter API entrypoint.

IMPORTANT:
The current working backend/main.py must first be renamed to
backend/main_legacy.py without changing its contents.

This thin entrypoint then loads the legacy application and replaces only the
live search orchestration with the robust central SearchEngine.
"""

import main_legacy as _legacy
from main_legacy import *
from search_engine import SearchEngine

import importlib
import json
import re
from typing import Any, Dict, List
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from fastapi import Query


# One central search engine, reusing the existing:
# - ProductMatcher
# - Family Registry
# - product catalog
# - eight store adapters
# - central validation/finalization functions
_engine = SearchEngine(_legacy)


# The FastAPI route functions live inside main_legacy.py and therefore resolve
# their globals in the legacy module's namespace.  Patch that namespace
# explicitly; assigning only local wrapper globals would NOT change the routes.
_legacy.search_perfume = _engine.search
_legacy._run_search_job = _engine.run_job
_legacy._search_job_snapshot = _engine.search_job_snapshot


# Keep the exact FastAPI application object and every existing route.
app = _legacy.app


# ===== TEMPORARY READ-ONLY NOTINO DEEP DIAGNOSTIC =====
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
    soup = BeautifulSoup(html, "html.parser")
    hrefs = []
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if href:
            hrefs.append({
                "href": href,
                "text": a.get_text(" ", strip=True)[:300],
            })

    product_href_re = re.compile(r"/p-\d+/?(?:[?#].*)?$", re.I)
    product_hrefs = [x for x in hrefs if product_href_re.search(x["href"].split("#", 1)[0])]

    raw_product_urls = sorted(set(re.findall(
        r"https?://(?:www\.)?notino\.fr/[^\"'<>\\s]+?/p-\d+/?",
        html,
        re.I,
    )))
    relative_product_urls = sorted(set(re.findall(
        r"(?:href|url|canonical|productUrl|product_url)[\\\"'=: ]+((?:https?:)?//(?:www\\.)?notino\\.fr)?[^\\\"'<>\\s]*?/p-\d+/?",
        html,
        re.I,
    )))

    jsonld_products: List[Dict[str, Any]] = []
    for script in soup.find_all("script", type=re.compile(r"ld\+json", re.I)):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                typ = item.get("@type")
                if typ == "Product" or (isinstance(typ, list) and "Product" in typ):
                    jsonld_products.append({
                        "name": item.get("name"),
                        "brand": item.get("brand"),
                        "sku": item.get("sku"),
                        "gtin": item.get("gtin13") or item.get("gtin"),
                        "url": item.get("url"),
                    })
                for value in item.values():
                    if isinstance(value, (dict, list)):
                        stack.append(value)

    text = soup.get_text(" ", strip=True)
    needles = [
        query,
        "9 PM",
        "Afnan",
        "AFN00282",
        "16167394",
        "9-am",
        "/p-",
        "100 ml",
        "36,00",
    ]

    try:
        module = importlib.import_module("scrapers.notino.scraper")
        extractor = getattr(module, "extract_candidates_from_html", None)
        extractor_result = None
        extractor_error = None
        if callable(extractor):
            try:
                extracted = extractor(html, query)
                extractor_result = {
                    "count": len(extracted or []),
                    "items": (extracted or [])[:20],
                }
            except Exception as exc:
                extractor_error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        extractor_result = None
        extractor_error = f"module_load: {type(exc).__name__}: {exc}"

    return {
        "html_length": len(html),
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
        "needles": [_snippet(html, n) for n in needles],
        "text_needles": [_snippet(text, n) for n in needles],
        "extractor": extractor_result,
        "extractor_error": extractor_error,
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
    meaningful = [t for t in tokens if t not in generic]
    if len(meaningful) >= 2:
        identity = " ".join(meaningful)
        if identity.casefold() != query.casefold():
            discovery_queries.append(identity)

    urls = []
    for dq in discovery_queries[:2]:
        qv = quote_plus(dq)
        urls.extend([
            f"{NOTINO_BASE}/search.asp?exps={qv}",
            f"{NOTINO_BASE}/search?query={qv}",
        ])

    reports = []
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
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
        "diagnostic": "notino-deep-read-only-v1",
        "query": query,
        "discovery_queries": discovery_queries[:2],
        "reports": reports,
    }

# ===== ON-DEMAND FORMAT PRICE COMPARISON =====
# Used by the product-detail view when a perfume has multiple real formats.
# The frontend sends the exact formats already known for that product.
# IMPORTANT: maximum 2 stores are queried concurrently, matching the main
# progressive search rule used by ScentHunter.
FORMAT_STORES = [
    "bplatz",
    "deloox",
    "parfumcity",
    "parfumzentrum",
    "perfumemarket",
    "sabina",
    "orioudh",
    "notino",
]


def _format_compare_num(value: Any) -> float:
    try:
        if value is None or value == "":
            return float("inf")
        return float(str(value).replace(",", "."))
    except Exception:
        raw = re.sub(r"[^0-9,.\-]", "", str(value))
        raw = raw.replace(",", ".")
        try:
            return float(raw)
        except Exception:
            return float("inf")


def _format_compare_size(candidate: Dict[str, Any]) -> int | None:
    raw = candidate.get("size_ml") or candidate.get("size")
    if raw is not None:
        m = re.search(r"(\d{1,4})", str(raw))
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass

    name = str(candidate.get("name") or "")
    m = re.search(r"\b(\d{1,4})\s*ml\b", name, flags=re.I)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    return None


def _format_compare_is_oos(candidate: Dict[str, Any]) -> bool:
    if candidate.get("in_stock") is False:
        return True
    text = " ".join(
        str(candidate.get(k) or "")
        for k in ("availability", "stock", "status", "name")
    ).casefold()
    markers = (
        "out of stock",
        "out-of-stock",
        "non disponibile",
        "nicht verfügbar",
        "indisponible",
        "rupture",
        "agotado",
        "esaurito",
    )
    return any(marker in text for marker in markers)


def _format_compare_clean_offer(
    candidate: Dict[str, Any],
    store: str,
    requested_size: int,
) -> Dict[str, Any]:
    offer = dict(candidate or {})
    offer["store"] = str(offer.get("store") or store)
    offer_size = _format_compare_size(offer)
    offer["size_ml"] = offer_size if offer_size is not None else requested_size
    if "price_value" not in offer:
        offer["price_value"] = _format_compare_num(offer.get("price"))
    offer["in_stock"] = not _format_compare_is_oos(offer)
    return offer


def _format_compare_query(product: str, size_ml: int) -> str:
    # Keep the exact product identity and append the explicit format.
    # This lets size-aware scrapers return the corresponding variant.
    return f"{product} {size_ml} ml".strip()


def _format_compare_store(store: str, product: str, size_ml: int) -> Dict[str, Any]:
    query = _format_compare_query(product, size_ml)
    try:
        raw = _legacy.run_store(store, query)
    except Exception as exc:
        return {
            "store": store,
            "size_ml": size_ml,
            "results": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    candidates = raw if isinstance(raw, list) else []
    # Reuse the central matcher/validator. We do NOT trust a raw scraper hit
    # merely because it contains a price.
    try:
        validated = _engine._validate_candidates_only(query, candidates)
    except Exception:
        validated = candidates

    cleaned = []
    for candidate in (validated or []):
        if not isinstance(candidate, dict):
            continue

        explicit_size = _format_compare_size(candidate)

        # STRICT FORMAT RULE.
        # The comparison is specifically per format. We must never take a
        # generic/first search result and label it 50 ml or 100 ml simply
        # because the query contained that number.
        #
        # - explicit wrong size => reject
        # - explicit requested size => accept
        # - missing size => reject (the scraper did not prove the variant)
        #
        # This is deliberately conservative: an absent price is preferable
        # to showing a false price for the wrong bottle size.
        if explicit_size is None:
            continue
        if explicit_size != size_ml:
            continue

        offer = _format_compare_clean_offer(candidate, store, size_ml)
        cleaned.append(offer)

    # One representative offer per store for this format.
    # Available offers beat OOS; then lower price wins.
    cleaned.sort(
        key=lambda o: (
            _format_compare_is_oos(o),
            _format_compare_num(o.get("price_value")),
        )
    )

    return {
        "store": store,
        "size_ml": size_ml,
        "results": cleaned[:1],
    }


@app.get("/compare-formats")
def compare_formats(
    q: str = Query(..., min_length=1),
    formats: str = Query("", min_length=0),
):
    product = str(q or "").strip()

    requested_sizes = []
    for raw_size in str(formats or "").split(","):
        m = re.search(r"(\d{1,4})", raw_size)
        if not m:
            continue
        try:
            value = int(m.group(1))
        except Exception:
            continue
        if value > 0 and value not in requested_sizes:
            requested_sizes.append(value)

    # No blind default formats here. The caller must send the real formats
    # known for the product; this prevents inventing 30/50/100 ml variants.
    requested_sizes.sort()

    if not requested_sizes:
        return {
            "ok": True,
            "query": product,
            "formats": [],
            "comparisons": [],
            "errors": {},
        }

    comparisons = []
    errors: Dict[str, str] = {}

    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Exactly 2 requests concurrently, regardless of format/store.
    # This is faster than waiting for a whole pair of stores to finish
    # before starting the next pair, while preserving the hard limit of 2.
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_map = {
            pool.submit(_format_compare_store, store, product, size): (store, size)
            for size in requested_sizes
            for store in FORMAT_STORES
        }

        for future in as_completed(future_map):
            store, size = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                errors[f"{store}:{size}"] = f"{type(exc).__name__}: {exc}"
                continue

            if result.get("error"):
                errors[f"{store}:{size}"] = result["error"]

            rows = result.get("results") or []
            if rows:
                comparisons.extend(rows)

    # Group the flat offers by requested format.
    by_size: Dict[int, List[Dict[str, Any]]] = {
        size: [] for size in requested_sizes
    }
    for offer in comparisons:
        try:
            size = int(offer.get("size_ml"))
        except Exception:
            continue
        if size in by_size:
            by_size[size].append(offer)

    formatted_comparisons = []
    for size in requested_sizes:
        offers = by_size[size]
        offers.sort(
            key=lambda o: (
                _format_compare_is_oos(o),
                _format_compare_num(o.get("price_value")),
            )
        )
        best = next(
            (o for o in offers if not _format_compare_is_oos(o)),
            None,
        )
        formatted_comparisons.append({
            "size_ml": size,
            "best": best,
            "offers": offers,
        })

    return {
        "ok": True,
        "query": product,
        "formats": requested_sizes,
        "comparisons": formatted_comparisons,
        "errors": errors,
    }
