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
import concurrent.futures
import time
import json
import math
import re
from typing import Any, Dict, List
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from fastapi import Query

_engine = SearchEngine(_legacy)

_original_product_identity_key = getattr(_legacy, "product_identity_key", None)
if callable(_original_product_identity_key):
    def _size_aware_product_identity_key(product):
        key = _original_product_identity_key(product)
        try:
            size = _legacy.product_size_ml(product)
        except Exception:
            size = None
        if size is None:
            return key
        if isinstance(key, tuple):
            return (*key, round(float(size), 4))
        return (key, round(float(size), 4))

    _legacy.product_identity_key = _size_aware_product_identity_key

_legacy.search_perfume = _engine.search
_legacy._run_search_job = _engine.run_job
_engine_snapshot = getattr(_engine, "search_job_snapshot", None)
if callable(_engine_snapshot):
    _legacy._search_job_snapshot = _engine_snapshot

app = _legacy.app

# IMPORTANT: the live /search-status endpoint must prepare the UI from the
# complete raw candidate pool, not from the last incremental validated slice.
# The previous snapshot consumed job["results"], which is intentionally
# rewritten after every store completes; depending on completion order this
# could make already-visible shops disappear from the final result.
# job["candidates"] is the monotonic source of truth for the current search.
def _search_job_snapshot_from_full_pool(job_id: str):
    lock = getattr(_legacy, "SEARCH_JOBS_LOCK", None)
    jobs = getattr(_legacy, "SEARCH_JOBS", None)

    if jobs is None:
        raise Exception("SEARCH_JOBS is not available")

    if lock is not None:
        with lock:
            job = jobs.get(job_id)
            if job is None:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Job di ricerca non trovato")
            query = str(job.get("query") or "")
            raw_candidates = list(job.get("candidates") or [])
            validated_candidates = list(job.get("validated_candidates") or [])
            errors = dict(job.get("errors") or {})
            completed = bool(job.get("completed"))
            store_status = dict(job.get("store_status") or {})
            diagnostics = dict(job.get("store_diagnostics") or {})
            phase = job.get("phase", "discovery")
    else:
        job = jobs.get(job_id)
        if job is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Job di ricerca non trovato")
        query = str(job.get("query") or "")
        raw_candidates = list(job.get("candidates") or [])
        validated_candidates = list(job.get("validated_candidates") or [])
        errors = dict(job.get("errors") or {})
        completed = bool(job.get("completed"))
        store_status = dict(job.get("store_status") or {})
        diagnostics = dict(job.get("store_diagnostics") or {})
        phase = job.get("phase", "discovery")

    try:
        # Use the monotonic validated pool produced by the background job.
        # Re-validating the whole raw pool here can make a store disappear if
        # a later scraper response for the same family is interpreted
        # differently. The job already validated each candidate when it was
        # discovered; that validated set is the source of truth for /search-status.
        validated = list(validated_candidates)
        if not validated:
            validated = _engine._validate_candidates_only(query, raw_candidates)
        results = _legacy._prepare_final_results(validated, query)
    except Exception as exc:
        print(
            "SEARCH_STATUS_FINALIZATION_ERROR:",
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        results = []

    return {
        "job_id": job_id,
        "query": query,
        "count": len(results),
        "results": results,
        "comparisons": [],
        "errors": errors,
        "store_status": store_status,
        "store_diagnostics": diagnostics,
        "phase": phase,
        "completed": completed,
        "status": "completed" if completed else "searching",
    }

_legacy._search_job_snapshot = _search_job_snapshot_from_full_pool

# ---------------------------------------------------------------------------
# MONOTONIC BACKGROUND SEARCH
# ---------------------------------------------------------------------------
# The stock SearchEngine job re-validates the complete raw pool at every
# publication. That is logically clean but operationally unsafe for live
# merchant adapters: a candidate that was valid in an earlier wave can be
# rejected by a later pass, so a shop visibly appears and then disappears.
#
# We keep two monotonic pools instead:
#   raw_candidates       = everything discovered so far
#   validated_candidates = everything that has passed validation at least once
# A validated offer is never removed during the same search job.
# /search-status consumes validated_candidates directly.

def _monotonic_result_key(item: Dict[str, Any]):
    """Identity of ONE retailer offer, never of the perfume family.

    A product identity is intentionally not enough here: Liquid Brun at
    Deloox and Liquid Brun at ParfumCity are two different offers and must
    both survive the incremental merge.
    """
    store = str(item.get("store") or item.get("shop") or "").strip().casefold()
    url = str(item.get("url") or item.get("product_url") or "").strip().casefold()

    try:
        identity = _legacy.product_identity_key(item)
    except Exception:
        identity = (
            str(item.get("name") or item.get("title") or "").strip().casefold(),
            str(item.get("brand") or item.get("source_brand") or "").strip().casefold(),
        )

    try:
        size = _engine._extract_candidate_size_ml(item)
    except Exception:
        size = None

    size_key = round(float(size), 4) if size is not None else None
    return (store, url, identity, size_key)


def _merge_monotonic_validated(existing: List[Dict[str, Any]],
                               new_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged = list(existing or [])
    seen = {_monotonic_result_key(item) for item in merged if isinstance(item, dict)}
    for item in new_items or []:
        if not isinstance(item, dict):
            continue
        key = _monotonic_result_key(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(item))
    return merged


def _monotonic_run_search_job(job_id: str, query: str) -> None:
    jobs = getattr(_legacy, "SEARCH_JOBS", None)
    lock = getattr(_legacy, "SEARCH_JOBS_LOCK", None)
    if jobs is None:
        raise RuntimeError("SEARCH_JOBS is not available")

    def update(payload: Dict[str, Any]) -> None:
        if lock is not None:
            with lock:
                job = jobs.get(job_id)
                if job is not None:
                    job.update(payload)
        else:
            job = jobs.get(job_id)
            if job is not None:
                job.update(payload)

    def exists() -> bool:
        if lock is not None:
            with lock:
                return jobs.get(job_id) is not None
        return jobs.get(job_id) is not None

    started = time.monotonic()
    raw_pool: List[Dict[str, Any]] = []
    validated_pool: List[Dict[str, Any]] = []
    store_status: Dict[str, Any] = {
        store: {"status": "pending", "count": 0}
        for store in _engine.stores
    }
    errors: Dict[str, str] = {}

    update({
        "completed": False,
        "phase": "discovery",
        "status": "searching",
        "results": [],
        "candidates": [],
        "validated_candidates": [],
        "errors": {},
        "store_status": store_status,
    })

    try:
        # Run the production search as two waves of four stores. This matches the
        # actual ScentHunter production search path while the validated pool
        # guarantees that completed offers remain visible.
        for wave_start in range(0, len(_engine.stores), 4):
            wave = _engine.stores[wave_start:wave_start + 4]

            update({
                "phase": f"stores_{wave_start + 1}_{wave_start + len(wave)}",
                "status": "searching",
                "store_status": {
                    **store_status,
                    **{store: {"status": "searching", "count": 0} for store in wave},
                },
            })

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=4,
                thread_name_prefix="scenthunter-store",
            ) as executor:
                future_map = {
                    executor.submit(_engine._run_one_store, store, query): store
                    for store in wave
                }

                for future in concurrent.futures.as_completed(future_map):
                    store = future_map[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = type("StoreRunFallback", (), {})()
                        result.store = store
                        result.status = "error"
                        result.candidates = []
                        result.elapsed = time.monotonic() - started
                        result.error = f"{type(exc).__name__}: {exc}"

                    candidates = [
                        item for item in (result.candidates or [])
                        if isinstance(item, dict)
                    ]
                    raw_pool.extend(candidates)

                    store_status[store] = {
                        "status": result.status,
                        "count": len(candidates),
                        "elapsed": round(float(result.elapsed), 3),
                        "error": result.error,
                    }
                    if result.error:
                        errors[store] = result.error

                    # Validate ONLY this store's candidates.
                    # Re-validating the complete cross-store pool here is the
                    # exact pattern that can make a previously valid retailer
                    # disappear when another retailer arrives with a similar
                    # product identity. Each store is authoritative for its
                    # own offers; the merge below is offer-level.
                    try:
                        current_validated = _engine._validate_candidates_only(
                            query,
                            list(candidates),
                        )
                    except Exception as exc:
                        print(
                            "STORE_VALIDATION_ERROR:",
                            f"store={store} {type(exc).__name__}: {exc}",
                            flush=True,
                        )
                        current_validated = []

                    validated_pool = _merge_monotonic_validated(
                        validated_pool,
                        current_validated,
                    )

                    update({
                        "results": list(validated_pool),
                        "candidates": list(raw_pool),
                        "validated_candidates": list(validated_pool),
                        "errors": dict(errors),
                        "store_status": dict(store_status),
                        "phase": f"stores_{wave_start + 1}_{wave_start + len(wave)}",
                        "status": "searching",
                        "completed": False,
                        "elapsed": round(time.monotonic() - started, 3),
                    })

            if not exists():
                return

        # Final publication uses the monotonic validated pool. No second
        # destructive validation pass is performed.
        update({
            "results": list(validated_pool),
            "candidates": list(raw_pool),
            "validated_candidates": list(validated_pool),
            "errors": dict(errors),
            "store_status": dict(store_status),
            "phase": "completed",
            "status": "completed",
            "completed": True,
            "elapsed": round(time.monotonic() - started, 3),
            "raw_candidate_count": len(raw_pool),
            "validated_candidate_count": len(validated_pool),
        })

    except Exception as exc:
        update({
            "results": list(validated_pool),
            "candidates": list(raw_pool),
            "validated_candidates": list(validated_pool),
            "errors": {**errors, "_search": f"{type(exc).__name__}: {exc}"},
            "status": "error",
            "completed": True,
            "phase": "error",
            "elapsed": round(time.monotonic() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
        })


_legacy._run_search_job = _monotonic_run_search_job

# Direct Shopify adapters for stores where the legacy adapter can lose the
# product during discovery. They are SUPPLEMENTS, never replacements: the
# legacy path stays authoritative for all stores, and direct candidates are
# merged by retailer + URL + size. This also lets a fresh Shopify stock flag
# correct a stale legacy OUT OF STOCK flag for the same product URL.
_original_run_store = _legacy.run_store
_DIRECT_SUPPLEMENT_STORES = {"parfumcity", "perfumemarket", "bplatz", "orioudh"}

_SHOPIFY_DIRECT_BASES = {
    "parfumcity": "https://www.parfumcity.nl",
    "perfumemarket": "https://www.perfumemarket.nl",
    "bplatz": "https://bplatz.de",
    "orioudh": "https://orioudh.com",
}


def _shopify_fallback_match(text: str, query: str) -> bool:
    def norm_tokens(value: str):
        value = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold())
        return {x for x in value.split() if len(x) > 1 and x not in {"ml", "cl"}}
    q = norm_tokens(query)
    return bool(q) and q.issubset(norm_tokens(text))


def _jina_read(url: str, timeout: int = 20) -> str:
    reader = "https://r.jina.ai/http://" + url.split("://", 1)[-1]
    try:
        response = requests.get(
            reader,
            headers={"User-Agent": "ScentHunter/1.0"},
            timeout=timeout,
        )
        if response.ok:
            return response.text or ""
    except Exception:
        pass
    return ""


def _shopify_jina_urls(store: str, query: str) -> List[str]:
    base = _SHOPIFY_DIRECT_BASES.get(store)
    if not base:
        return []
    q = quote_plus(str(query or "").strip())
    search_urls = (
        f"{base}/search?q={q}&type=product",
        f"{base}/nl/search?q={q}&type=product",
        f"{base}/en/search?q={q}&type=product",
    )
    domain = re.escape(base.split("//", 1)[-1])
    found: List[str] = []
    seen = set()
    for search_url in search_urls:
        text = _jina_read(search_url, timeout=18)
        if not text:
            continue
        patterns = [
            rf"https?://(?:www\\.)?{domain}/[^\\s)\\]\\\"]*/products/[^\\s)\\]\\\"]+",
            r"(?:https?://)?[^\\s)\\]\\\"]*/products/[^\\s)\\]\\\"]+",
        ]
        for pattern in patterns:
            for raw in re.findall(pattern, text, re.I):
                raw = raw.rstrip(".,;\\\")'\\]")
                if not raw.startswith("http"):
                    raw = base.rstrip("/") + "/" + raw.lstrip("/")
                raw = raw.split("?", 1)[0].split("#", 1)[0].rstrip("/")
                if "/products/" not in raw:
                    continue
                if not _shopify_fallback_match(raw, query):
                    continue
                if raw not in seen:
                    seen.add(raw)
                    found.append(raw)
    return found[:20]


def _shopify_json_fallback(store: str, query: str) -> List[Dict[str, Any]]:
    urls = _shopify_jina_urls(store, query)
    if not urls:
        return []
    out: List[Dict[str, Any]] = []
    for url in urls:
        try:
            response = requests.get(
                url.rstrip("/") + ".js",
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
                    "Accept": "application/json,text/plain,*/*",
                },
                timeout=12,
            )
            if not response.ok:
                continue
            data = response.json()
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        title = str(data.get("title") or "").strip()
        vendor = str(data.get("vendor") or "").strip()
        if not title or not _shopify_fallback_match(f"{title} {vendor} {url}", query):
            continue
        variants = data.get("variants") or []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            raw_price = variant.get("price")
            try:
                price = float(raw_price)
                if price >= 100:
                    price /= 100.0
            except (TypeError, ValueError):
                continue
            vtitle = str(variant.get("title") or "").strip()
            size_match = re.search(r"(?<!\\d)(\\d+(?:[.,]\\d+)?)\\s*(ml|cl)\\b", f"{vtitle} {title}", re.I)
            size = None
            if size_match:
                size = float(size_match.group(1).replace(",", "."))
                if size_match.group(2).casefold() == "cl":
                    size *= 10
                if size.is_integer():
                    size = int(size)
            available = variant.get("available")
            stock = "in_stock" if available is True else "out_of_stock" if available is False else "unknown"
            name = title if not vtitle or vtitle.casefold() == "default title" else f"{title} {vtitle}"
            out.append({
                "store": store,
                "name": name,
                "brand": vendor or None,
                "canonical_name": title,
                "size_ml": size,
                "extracted_size_ml": size,
                "price": f"{price:.2f}".replace(".", ",") + " €",
                "available": available,
                "in_stock": available,
                "availability": stock,
                "url": url,
                "product_id": data.get("id"),
                "sku": variant.get("sku"),
                "source": {"source_name": name, "source_brand": vendor or None, "url": url, "image": data.get("featured_image")},
                "offer": {"price": price, "currency": "EUR", "availability": stock},
                "attributes": {"size_ml": {"value": size, "source": "shopify_variant"} if size is not None else None},
            })
    return out


def _run_store_with_direct_supplements(store: str, query: str):
    store_key = str(store or "").strip().casefold()
    if store_key not in _DIRECT_SUPPLEMENT_STORES:
        try:
            raw_primary = _original_run_store(store, query)
            return list(raw_primary or [])
        except Exception as exc:
            print(
                "LEGACY_STORE_SEARCH_ERROR:",
                f"store={store_key} {type(exc).__name__}: {exc}",
                flush=True,
            )
            return []

    # The Shopify stores are discovered directly first. This is deliberate:
    # the old PerfumeMarket adapter can spend ~90 seconds walking fallback
    # sitemaps before returning an empty list. That blocks the whole search
    # even though the live product is present.
    direct = []
    # PerfumeMarket's legacy Shopify crawler is the known ~90s failure point.
    # Skip it entirely and use bounded live URL discovery instead.
    if store_key == "perfumemarket":
        direct = _shopify_json_fallback(store_key, str(query or "").strip())
    else:
        try:
            module = importlib.import_module(f"scrapers.{store_key}.scraper")
            search_fn = getattr(module, "search", None)
            if callable(search_fn):
                direct = search_fn(str(query or "").strip()) or []
        except Exception as exc:
            print(
                "DIRECT_STORE_SEARCH_ERROR:",
                f"store={store_key} {type(exc).__name__}: {exc}",
                flush=True,
            )

        if not direct:
            direct = _shopify_json_fallback(store_key, str(query or "").strip())

    # Only after direct discovery has failed do we allow the legacy adapter a
    # bounded fallback for ParfumCity/Bplatz/Orioudh. PerfumeMarket's old
    # sitemap path is intentionally never allowed to block the live search.
    if not direct and store_key != "perfumemarket":
        try:
            raw_primary = _original_run_store(store_key, query)
            direct = list(raw_primary or [])
        except Exception as exc:
            print(
                "LEGACY_STORE_SEARCH_ERROR:",
                f"store={store_key} {type(exc).__name__}: {exc}",
                flush=True,
            )
    primary = list(direct or [])

    merged = []
    seen = set()

    def add(item):
        if not isinstance(item, dict):
            return
        url = str(item.get("url") or item.get("product_url") or "").strip().casefold()
        try:
            size = _engine._extract_candidate_size_ml(item)
        except Exception:
            size = None
        key = (url, round(float(size), 4) if size is not None else None)
        if key in seen:
            return
        seen.add(key)
        merged.append(item)

    # Direct first: it reads the live Shopify product JSON and therefore has
    # the freshest price/stock flag. The legacy result is used as fallback
    # only when the direct adapter did not return that exact URL+size.
    for item in direct:
        add(item)
    for item in primary:
        add(item)

    return merged

_legacy.run_store = _run_store_with_direct_supplements

# SearchEngine resolves the store adapter through the legacy module. Keep the
# method explicit as well so direct supplements are used regardless of whether
# the engine cached the callable during initialization.
_original_engine_run_one_store = _engine._run_one_store

def _engine_run_one_store_with_supplements(store: str, query: str):
    store_key = str(store or "").strip().casefold()
    if store_key in _DIRECT_SUPPLEMENT_STORES:
        try:
            candidates = _run_store_with_direct_supplements(store_key, query)
            return type("StoreRun", (), {
                "store": store_key,
                "status": "ok" if candidates else "empty",
                "candidates": candidates,
                "elapsed": 0.0,
                "error": None,
            })()
        except Exception as exc:
            return type("StoreRun", (), {
                "store": store_key,
                "status": "error",
                "candidates": [],
                "elapsed": 0.0,
                "error": f"{type(exc).__name__}: {exc}",
            })()
    return _original_engine_run_one_store(store, query)

_engine._run_one_store = _engine_run_one_store_with_supplements

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
    product_hrefs = [
        x for x in hrefs
        if product_href_re.search(x["href"].split("#", 1)[0])
    ]

    raw_product_urls = sorted(set(re.findall(
        r"https?://(?:www\.)?notino\.fr/[^\"'<> \s]+?/p-\d+/?",
        html,
        re.I,
    )))
    relative_product_urls = sorted(set(re.findall(
        r"(?:href|url|canonical|productUrl|product_url)[\"'=: ]+((?:https?:)?//(?:www\.)?notino\.fr)?[^\"'<> \s]*?/p-\d+/?",
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
                if typ == "Product" or (
                    isinstance(typ, list) and "Product" in typ
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
                        stack.append(value)

    text = soup.get_text(" ", strip=True)
    needles = [
        query, "9 PM", "Afnan", "AFN00282", "16167394",
        "9-am", "/p-", "100 ml", "36,00",
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
            response = session.get(
                reader_url, timeout=30, allow_redirects=True
            )
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


def _format_compare_num(value: Any) -> float | None:
    """
    Return a JSON-safe numeric price for sorting.

    Never return +/-inf or NaN because those values can make Starlette/FastAPI
    reject an otherwise valid JSON response with HTTP 500.
    """
    if value is None or value == "":
        return None

    try:
        number = float(str(value).replace(",", "."))
    except Exception:
        raw = re.sub(r"[^0-9,.\-]", "", str(value))
        raw = raw.replace(",", ".")
        try:
            number = float(raw)
        except Exception:
            return None

    if not math.isfinite(number):
        return None
    return number


def _format_compare_sort_price(value: Any) -> float:
    number = _format_compare_num(value)
    return number if number is not None else float("inf")


def _format_compare_size(candidate: Dict[str, Any]) -> int | None:
    """Extract an explicit bottle size from both legacy and structured offers."""
    value = None

    extractor = getattr(_legacy, "product_size_ml", None)
    if callable(extractor):
        try:
            value = extractor(candidate)
        except Exception:
            value = None

    # The newer Shopify adapters expose size inside attributes/raw_data.
    # The legacy extractor only checks top-level fields, so use the SearchEngine
    # extractor as a lossless fallback before rejecting an otherwise valid offer.
    if value in (None, ""):
        engine_extractor = getattr(_engine, "_extract_candidate_size_ml", None)
        if callable(engine_extractor):
            try:
                value = engine_extractor(candidate)
            except Exception:
                value = None

    if value in (None, ""):
        return None

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(numeric) or numeric <= 0:
        return None

    return int(numeric) if numeric.is_integer() else int(round(numeric))


def _format_compare_stock_state(candidate: Dict[str, Any]) -> str:
    """Return the normalized stock state without inventing availability."""
    if candidate.get("in_stock") is True:
        return "in_stock"
    if candidate.get("in_stock") is False:
        return "out_of_stock"

    available = candidate.get("available")
    if available is True:
        return "in_stock"
    if available is False:
        return "out_of_stock"

    text = " ".join(
        str(candidate.get(k) or "")
        for k in ("availability", "stock", "status")
    ).casefold()

    out_markers = (
        "out of stock",
        "out-of-stock",
        "non disponibile",
        "nicht verfügbar",
        "indisponible",
        "rupture",
        "agotado",
        "esaurito",
        "unavailable",
    )
    if any(marker in text for marker in out_markers):
        return "out_of_stock"

    in_markers = (
        "in stock",
        "in-stock",
        "disponibile",
        "disponible",
        "available",
        "en stock",
        "auf lager",
        "disponible ahora",
    )
    if any(marker in text for marker in in_markers):
        return "in_stock"

    return "unknown"


def _format_compare_is_oos(candidate: Dict[str, Any]) -> bool:
    return _format_compare_stock_state(candidate) == "out_of_stock"


def _format_compare_clean_offer(
    candidate: Dict[str, Any],
    store: str,
    requested_size: int,
) -> Dict[str, Any]:
    offer = dict(candidate or {})
    offer["store"] = str(offer.get("store") or store)

    offer_size = _format_compare_size(offer)
    if offer_size is None:
        raise ValueError("Cannot create format offer without explicit size_ml")
    if offer_size != requested_size:
        raise ValueError(
            f"Offer size {offer_size} does not match requested size "
            f"{requested_size}"
        )

    offer["size_ml"] = offer_size

    # Keep price_value JSON-safe. Missing/unparseable prices are represented
    # by null rather than Infinity.
    price_value = _format_compare_num(offer.get("price_value"))
    if price_value is None:
        price_value = _format_compare_num(offer.get("price"))
    offer["price_value"] = price_value

    stock_state = _format_compare_stock_state(offer)
    offer["availability"] = stock_state
    if stock_state == "in_stock":
        offer["in_stock"] = True
    elif stock_state == "out_of_stock":
        offer["in_stock"] = False
    else:
        offer["in_stock"] = None
    return offer


def _format_compare_query(
    product: str,
    requested_size: int | None = None,
) -> str:
    base = str(product or "").strip()
    if requested_size is None:
        return base
    return f"{base} {int(requested_size)} ml"


def _format_compare_store(
    store: str,
    product: str,
    requested_size: int,
) -> Dict[str, Any]:
    # Do NOT put the bottle size into the retailer search query.
    # The forensic diagnostic proved that several adapters return 0 results
    # for "liquid brun 100 ml" even though the same adapters return the real
    # 100 ml candidates for the base query "liquid brun".
    # Discovery stays broad; explicit size extraction below is authoritative.
    query = _format_compare_query(product)

    try:
        raw = _legacy.run_store(store, query)
    except Exception as exc:
        return {
            "store": store,
            "requested_size": requested_size,
            "results": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    candidates = raw if isinstance(raw, list) else []
    normalized_candidates = []

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue

        item = dict(candidate)
        size = _format_compare_size(item)

        if size is None or size != requested_size:
            continue

        item["size_ml"] = size
        item["size_source"] = item.get(
            "size_source",
            "central_product_size_ml",
        )
        normalized_candidates.append(item)

    try:
        validated = _engine._validate_candidates_only(
            product,
            normalized_candidates,
        )
    except Exception:
        validated = normalized_candidates

    cleaned = []
    for candidate in validated or []:
        if not isinstance(candidate, dict):
            continue

        explicit_size = _format_compare_size(candidate)
        if explicit_size != requested_size:
            continue

        item = dict(candidate)
        item["size_ml"] = explicit_size

        try:
            cleaned.append(
                _format_compare_clean_offer(
                    item, store, requested_size
                )
            )
        except ValueError:
            continue

    cleaned.sort(
        key=lambda offer: (
            _format_compare_is_oos(offer),
            _format_compare_sort_price(offer.get("price_value")),
        )
    )

    return {
        "store": store,
        "requested_size": requested_size,
        "results": cleaned,
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

    jobs = [
        (store, size)
        for size in requested_sizes
        for store in FORMAT_STORES
    ]

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_map = {
            pool.submit(
                _format_compare_store,
                store,
                product,
                size,
            ): (store, size)
            for store, size in jobs
        }

        for future in as_completed(future_map):
            store, size = future_map[future]
            key = f"{store}:{size}"
            try:
                result = future.result()
            except Exception as exc:
                errors[key] = f"{type(exc).__name__}: {exc}"
                continue

            if result.get("error"):
                errors[key] = result["error"]

            comparisons.extend(result.get("results") or [])

    by_size: Dict[int, List[Dict[str, Any]]] = {
        size: [] for size in requested_sizes
    }

    for offer in comparisons:
        if not isinstance(offer, dict):
            continue

        raw_size = offer.get("size_ml")
        if raw_size in (None, ""):
            continue

        try:
            size = int(float(raw_size))
        except (TypeError, ValueError):
            continue

        if size not in by_size:
            continue

        by_size[size].append(offer)

    formatted_comparisons = []
    for size in requested_sizes:
        offers = by_size[size]
        offers.sort(
            key=lambda o: (
                _format_compare_is_oos(o),
                _format_compare_sort_price(o.get("price_value")),
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


import time as _diag_time
from concurrent.futures import (
    ThreadPoolExecutor as _DiagPool,
    as_completed as _diag_as_completed,
)


@app.get("/diagnose-format-flow")
def diagnose_format_flow(
    q: str = Query(..., min_length=1),
    formats: str = Query(..., min_length=1),
    budget: int = Query(90, ge=5, le=300),
):
    product = str(q or "").strip()
    sizes = []

    for token in re.findall(r"\d{1,4}", str(formats or "")):
        n = int(token)
        if 1 <= n <= 2000 and n not in sizes:
            sizes.append(n)

    sizes.sort()
    started = _diag_time.monotonic()
    jobs = [
        (store, size)
        for size in sizes
        for store in FORMAT_STORES
    ]
    rows = []

    def one(store, size):
        t0 = _diag_time.monotonic()

        # Diagnostic discovery must stay broad too. The requested size is
        # filtered after discovery; several retailer search engines return
        # zero results when "100 ml" is appended to the query even though
        # the 100 ml product is present for the base query.
        query = _format_compare_query(product)

        out = {
            "store": store,
            "requested_size_ml": size,
            "query": query,
            "elapsed_ms": None,
            "raw_count": 0,
            "validated_count": 0,
            "explicit_size_counts": {},
            "accepted_count": 0,
            "accepted": [],
            "rejected": [],
            "error": None,
        }

        try:
            raw = _legacy.run_store(store, query)
            candidates = raw if isinstance(raw, list) else []
            out["raw_count"] = len(candidates)

            try:
                validated = _engine._validate_candidates_only(
                    product, candidates
                )
            except Exception as exc:
                out["validation_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                validated = candidates

            validated = validated or []
            out["validated_count"] = len(validated)

            for c in validated:
                if not isinstance(c, dict):
                    continue

                sz = _format_compare_size(c)
                key = "missing" if sz is None else str(sz)
                out["explicit_size_counts"][key] = (
                    out["explicit_size_counts"].get(key, 0) + 1
                )

                item = {
                    "name": c.get("name"),
                    "brand": c.get("brand"),
                    "size_ml": sz,
                    "size": c.get("size"),
                    "price": c.get("price"),
                    "price_value": c.get("price_value"),
                    "in_stock": c.get("in_stock"),
                    "url": c.get("url") or c.get("product_url"),
                    "sku": c.get("sku"),
                    "gtin": (
                        c.get("gtin")
                        or c.get("ean")
                        or c.get("gtin13")
                    ),
                }

                if sz == size:
                    out["accepted"].append(item)
                else:
                    reason = (
                        "missing_size"
                        if sz is None
                        else f"wrong_size:{sz}"
                    )
                    item["reject_reason"] = reason
                    out["rejected"].append(item)

            out["accepted_count"] = len(out["accepted"])
            out["accepted"] = out["accepted"][:10]
            out["rejected"] = out["rejected"][:20]

        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            out["elapsed_ms"] = round(
                (_diag_time.monotonic() - t0) * 1000
            )

        return out

    with _DiagPool(max_workers=2) as pool:
        fmap = {
            pool.submit(one, store, size): (store, size)
            for store, size in jobs
        }

        for fut in _diag_as_completed(fmap):
            store, size = fmap[fut]
            try:
                rows.append(fut.result())
            except Exception as exc:
                rows.append({
                    "store": store,
                    "requested_size_ml": size,
                    "error": (
                        f"future:{type(exc).__name__}: {exc}"
                    ),
                })

            if (_diag_time.monotonic() - started) > budget:
                break

    rows.sort(
        key=lambda x: (
            int(x.get("requested_size_ml") or 0),
            str(x.get("store") or ""),
        )
    )

    by_size = {}
    for row in rows:
        by_size.setdefault(
            str(row.get("requested_size_ml")),
            []
        ).append(row)

    return {
        "ok": True,
        "diagnostic": "format_flow_read_only_v2",
        "query": product,
        "requested_formats": sizes,
        "stores": FORMAT_STORES,
        "max_concurrency": 2,
        "budget_seconds": budget,
        "elapsed_total_ms": round(
            (_diag_time.monotonic() - started) * 1000
        ),
        "completed_jobs": len(rows),
        "expected_jobs": len(jobs),
        "budget_exceeded": (
            (_diag_time.monotonic() - started) > budget
        ),
        "by_format": by_size,
        "jobs": rows,
    }


@app.get("/diagnose-deloox-disappearance")
def diagnose_deloox_disappearance(
    q: str = Query("liquid brun", min_length=1)
):
    try:
        from diagnostic_search import run_query
    except Exception as exc:
        return {
            "ok": False,
            "diagnostic_stage": "import",
            "query": str(q or "").strip(),
            "error": f"{type(exc).__name__}: {exc}",
        }

    try:
        return run_query(str(q or "").strip())
    except Exception as exc:
        return {
            "ok": False,
            "diagnostic_stage": "execution",
            "query": str(q or "").strip(),
            "error": f"{type(exc).__name__}: {exc}",
        }

# ---------------------------------------------------------------------------
# FINAL LIVE /search ORCHESTRATION
# ---------------------------------------------------------------------------
# The frontend calls /search once and waits for ONE final JSON response.
# Therefore the async /search-status machinery above is not the path used by
# the live UI.  The authoritative fix is here: execute every store, retry
# stores that return no candidates, validate each store independently, merge
# without deleting earlier offers, and prepare the final result only once.
# ---------------------------------------------------------------------------

def _stable_live_search(query: str) -> Dict[str, Any]:
    started = time.monotonic()
    text = str(query or "").strip()
    if not text:
        return {"query": text, "count": 0, "results": [], "errors": {}}

    stores = list(_engine.stores)
    all_validated: List[Dict[str, Any]] = []
    all_raw: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}
    store_reports: Dict[str, Any] = {}
    lock = concurrent.futures.thread.Lock() if hasattr(concurrent.futures.thread, "Lock") else None

    # Offer-level identity. Store is mandatory so Deloox/Sabina/etc. can
    # never collide with the same perfume from another merchant.
    def offer_key(item: Dict[str, Any]):
        store = str(item.get("store") or item.get("shop") or "").strip().casefold()
        url = str(item.get("url") or item.get("product_url") or "").strip().casefold().split("?", 1)[0]
        try:
            size = _engine._extract_candidate_size_ml(item)
        except Exception:
            size = None
        try:
            identity = _legacy.product_identity_key(item)
        except Exception:
            identity = (
                str(item.get("brand") or "").strip().casefold(),
                str(item.get("name") or item.get("title") or "").strip().casefold(),
            )
        return (store, url, identity, round(float(size), 4) if size is not None else None)

    def merge(existing: List[Dict[str, Any]], new_items: List[Dict[str, Any]]):
        out = list(existing)
        seen = {offer_key(x) for x in out if isinstance(x, dict)}
        for item in new_items or []:
            if not isinstance(item, dict):
                continue
            key = offer_key(item)
            if key in seen:
                continue
            seen.add(key)
            out.append(dict(item))
        return out

    def run_store(store: str):
        store_started = time.monotonic()
        attempts = []
        best_candidates: List[Dict[str, Any]] = []
        last_error = None
        final_status = "empty"

        # Two complete attempts are enough to recover transient empty/429/403
        # discovery responses without allowing one broken merchant to consume
        # the whole request budget.
        for attempt in range(1, 3):
            try:
                result = _engine._run_one_store(store, text)
                candidates = [x for x in (result.candidates or []) if isinstance(x, dict)]
                status = str(result.status or ("ok" if candidates else "empty"))
                error = result.error
                attempts.append({
                    "attempt": attempt,
                    "status": status,
                    "count": len(candidates),
                    "error": error,
                })
                if candidates:
                    best_candidates = candidates
                    final_status = "ok"
                    last_error = None
                    break
                last_error = error
                final_status = status
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                final_status = "error"
                attempts.append({
                    "attempt": attempt,
                    "status": "error",
                    "count": 0,
                    "error": last_error,
                })

        elapsed = round(time.monotonic() - store_started, 3)
        return store, best_candidates, {
            "status": final_status,
            "count": len(best_candidates),
            "elapsed": elapsed,
            "attempts": attempts,
            "error": last_error,
        }

    # Four stores at a time: this matches the intended 2 waves x 4-store
    # production model while keeping a bounded number of browser/http jobs.
    for wave_start in range(0, len(stores), 4):
        wave = stores[wave_start:wave_start + 4]
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(wave),
            thread_name_prefix="scenthunter-live",
        ) as executor:
            futures = {executor.submit(run_store, store): store for store in wave}
            for future in concurrent.futures.as_completed(futures):
                store = futures[future]
                try:
                    store_name, candidates, report = future.result()
                except Exception as exc:
                    store_name = store
                    candidates = []
                    report = {
                        "status": "error",
                        "count": 0,
                        "elapsed": 0,
                        "attempts": [],
                        "error": f"{type(exc).__name__}: {exc}",
                    }

                store_reports[store_name] = report
                all_raw = merge(all_raw, candidates)

                try:
                    validated = _engine._validate_candidates_only(text, list(candidates))
                except Exception as exc:
                    validated = []
                    report["validation_error"] = f"{type(exc).__name__}: {exc}"

                all_validated = merge(all_validated, validated)
                if report.get("error") and not candidates:
                    errors[store_name] = str(report["error"])

        # If the complete first wave is already taking too long, do not start
        # an unbounded third/fourth wave. The two-wave contract is intentional.
        if time.monotonic() - started > 175:
            for remaining in stores[wave_start + 4:]:
                store_reports.setdefault(remaining, {
                    "status": "timeout",
                    "count": 0,
                    "elapsed": round(time.monotonic() - started, 3),
                    "attempts": [],
                    "error": "Global search budget exceeded",
                })
            break

    try:
        results = _legacy._prepare_final_results(list(all_validated), text)
    except Exception as exc:
        print("LIVE_SEARCH_FINALIZATION_ERROR:", repr(exc), flush=True)
        results = []
        errors["_finalization"] = f"{type(exc).__name__}: {exc}"

    return {
        "query": text,
        "count": len(results),
        "results": results,
        "comparisons": [],
        "errors": errors,
        "store_status": store_reports,
        "raw_candidate_count": len(all_raw),
        "validated_candidate_count": len(all_validated),
        "elapsed": round(time.monotonic() - started, 3),
    }


# IMPORTANT: this assignment is deliberately LAST.  main_legacy.search()
# resolves search_perfume from its own module globals at request time, so the
# frontend /search endpoint now uses the stable all-store path above.
_legacy.search_perfume = _stable_live_search
