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


# ---------------------------------------------------------------------------
# VALIDATED /test-store PIPELINE
# ---------------------------------------------------------------------------
# The progressive frontend calls /test-store directly.  The legacy endpoint
# returns raw scraper candidates, which means a broad retailer hit such as
# "Hawas For Him" or "Hawas Pink" can reach the UI even when the requested
# variant is "Hawas For Her".  The normal /search route already has the central
# Family Registry validation, so this wrapper gives /test-store the same
# identity gate while keeping the per-store response shape unchanged.

_original_run_store = _legacy.run_store


def _merge_store_candidates(*groups):
    merged = []
    seen = set()
    for group in groups:
        for item in group or []:
            if not isinstance(item, dict):
                continue
            try:
                key = _legacy.product_identity_key(item)
            except Exception:
                key = (
                    str(item.get("store") or "").strip().lower(),
                    str(item.get("url") or "").strip().lower(),
                    str(item.get("name") or item.get("title") or "").strip().lower(),
                    str(item.get("size_ml") or item.get("size") or "").strip(),
                )
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def _catalog_discovery_queries(query: str):
    """Return only authoritative aliases for a specific catalog variant."""
    try:
        family = _legacy._catalog_family_for_query(query)
        if family is None:
            return []
        query_key = _legacy.catalog_variant_key(query)
        if query_key in family.get("normalized_query_aliases", ()):
            return []
        requested = _legacy._catalog_requested_variant(query, family)
        if not isinstance(requested, dict):
            return []

        canonical = str(requested.get("canonical_name") or "").strip()
        aliases = [str(x or "").strip() for x in (requested.get("aliases") or [])]
        # Prefer a retailer-friendly gender alias after the canonical name.
        # This is especially useful when the shop search endpoint ignores
        # "for her/for him" wording in a full query.
        preferred = []
        for alias in aliases:
            low = _legacy.norm(alias)
            if any(token in low.split() for token in ("women", "femme", "dames", "donna")):
                preferred.append(alias)
        values = [canonical] + preferred + aliases
        out = []
        seen = set()
        for value in values:
            value = str(value or "").strip()
            key = _legacy.norm(value)
            if not key or key in seen:
                continue
            if key == _legacy.norm(query):
                continue
            seen.add(key)
            out.append(value)
            if len(out) >= 2:
                break
        return out
    except Exception:
        return []


def _validated_store_results(store: str, query: str):
    first = _original_run_store(store, query) or []
    validated = _engine._validate_candidates_only(query, first)
    if validated:
        return _merge_store_candidates(validated)

    # If discovery found only false variants (common with gendered product
    # names), retry using the Registry's exact canonical name/aliases.
    extra_groups = []
    for discovery_query in _catalog_discovery_queries(query):
        try:
            candidates = _original_run_store(store, discovery_query) or []
            extra_groups.append(candidates)
            validated = _engine._validate_candidates_only(
                query,
                _merge_store_candidates(first, *extra_groups),
            )
            if validated:
                return _merge_store_candidates(validated)
        except Exception:
            continue

    return _merge_store_candidates(
        _engine._validate_candidates_only(
            query,
            _merge_store_candidates(first, *extra_groups),
        )
    )


# Replace the already-registered legacy /test-store route in-place.  This keeps
# the public URL identical, so the existing frontend does not need a new API.
for _route in getattr(_legacy.app.router, "routes", []):
    if getattr(_route, "path", None) == "/test-store":
        def _validated_test_store(store: str, q: str):
            store_name = str(store or "").strip().lower()
            query = str(q or "").strip()

            if store_name not in _legacy.STORES:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Store non valido. Disponibili: "
                        + ", ".join(_legacy.STORES)
                    ),
                )
            if not query:
                raise HTTPException(
                    status_code=400,
                    detail="Parametro q mancante",
                )

            try:
                results = _validated_store_results(store_name, query)
                return {
                    "store": store_name,
                    "query": query,
                    "count": len(results),
                    "results": _legacy.sort_by_price(
                        _legacy.unique_results(results)
                    ),
                }
            except Exception as error:
                traceback.print_exc()
                return {
                    "store": store_name,
                    "query": query,
                    "count": 0,
                    "results": [],
                    "error": f"{type(error).__name__}: {error}",
                }

        _route.endpoint = _validated_test_store
        try:
            _route.dependant.call = _validated_test_store
        except Exception:
            pass
        break


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
