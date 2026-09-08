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

# Keep size variants from the same retailer product URL/product-id distinct.
# The legacy deduplicator historically keyed product-id results without size,
# which collapses 30/50/100 ml variants into the first one seen.
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

# The FastAPI route functions live inside main_legacy.py and therefore resolve
# their globals in the legacy module's namespace. Patch that namespace
# explicitly; assigning only local wrapper globals would NOT change the routes.
_legacy.search_perfume = _engine.search
_legacy._run_search_job = _engine.run_job
# The restored SearchEngine does not expose search_job_snapshot().
# Keep the legacy snapshot function when that optional method is absent.
_engine_snapshot = getattr(_engine, "search_job_snapshot", None)
if callable(_engine_snapshot):
    _legacy._search_job_snapshot = _engine_snapshot

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
        r"https?://(?:www\.)?notino\.fr/[^\"'<>\s]+?/p-\d+/?",
        html,
        re.I,
    )))
    relative_product_urls = sorted(set(re.findall(
        r"(?:href|url|canonical|productUrl|product_url)[\"'=: ]+((?:https?:)?//(?:www\.)?notino\.fr)?[^\"'<>\s]*?/p-\d+/?",
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

def _format_compare_size(
    candidate: Dict[str, Any],
) -> int | None:
    """
    Usa esclusivamente l'estrattore centrale del backend.
    Non duplicare qui la logica size_ml.
    """
    extractor = getattr(_legacy, "product_size_ml", None)

    if not callable(extractor):
        return None

    try:
        value = extractor(candidate)
    except Exception:
        return None

    if value in (None, ""):
        return None

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    return int(numeric) if numeric.is_integer() else int(round(numeric))

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

    offer["store"] = str(
        offer.get("store") or store
    )

    offer_size = _format_compare_size(offer)

    if offer_size is None:
        raise ValueError(
            "Cannot create format offer without explicit size_ml"
        )

    if offer_size != requested_size:
        raise ValueError(
            f"Offer size {offer_size} does not match "
            f"requested size {requested_size}"
        )

    offer["size_ml"] = offer_size

    if "price_value" not in offer:
        offer["price_value"] = _format_compare_num(
            offer.get("price")
        )

    offer["in_stock"] = not _format_compare_is_oos(
        offer
    )

    return offer

def _format_compare_query(product: str, requested_size: int | None = None) -> str:
    """Build an explicit store query for one requested bottle size.

    A format comparison must not run one generic store search and then pretend
    that its first result represents every requested size. The size is therefore
    part of discovery, while acceptance still requires an explicit parsed size.
    """
    base = str(product or "").strip()
    if requested_size is None:
        return base
    return f"{base} {int(requested_size)} ml"

def _format_compare_store(
    store: str,
    product: str,
    requested_size: int,
) -> Dict[str, Any]:
    """Search one store for exactly one requested format.

    The scraper is never allowed to have a missing size silently assigned to
    the requested format. A candidate is accepted only when the scraper/backend
    extracts an explicit size equal to ``requested_size``.
    """
    query = _format_compare_query(product, requested_size)

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

        # Critical safety rule: missing size is NOT the requested size.
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
                    item,
                    store,
                    requested_size,
                )
            )
        except ValueError:
            continue

    cleaned.sort(
        key=lambda offer: (
            _format_compare_is_oos(offer),
            _format_compare_num(offer.get("price_value")),
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

    # True format comparison: every store/format pair is a separate discovery
    # query. No result with a missing size can be relabelled as another format.
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

    # Group the flat offers by requested format.
    by_size: Dict[int, List[Dict[str, Any]]] = {
        size: []
        for size in requested_sizes
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

# ===== READ-ONLY FORMAT FLOW DIAGNOSTIC =====
# This endpoint does not alter any existing search route. It executes the same
# store calls used by /compare-formats and exposes every stage so we can see
# exactly where a 2-format or 3-format flow fails.
import time as _diag_time
from concurrent.futures import ThreadPoolExecutor as _DiagPool, as_completed as _diag_as_completed

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
    jobs = [(store, size) for size in sizes for store in FORMAT_STORES]
    rows = []

    def one(store, size):
        t0 = _diag_time.monotonic()
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
                validated = _engine._validate_candidates_only(product, candidates)
            except Exception as exc:
                out["validation_error"] = f"{type(exc).__name__}: {exc}"
                validated = candidates
            validated = validated or []
            out["validated_count"] = len(validated)
            for c in validated:
                if not isinstance(c, dict):
                    continue
                sz = _format_compare_size(c)
                key = "missing" if sz is None else str(sz)
                out["explicit_size_counts"][key] = out["explicit_size_counts"].get(key, 0) + 1
                item = {
                    "name": c.get("name"),
                    "brand": c.get("brand"),
                    "size_ml": c.get("size_ml"),
                    "size": c.get("size"),
                    "price": c.get("price"),
                    "price_value": c.get("price_value"),
                    "in_stock": c.get("in_stock"),
                    "url": c.get("url") or c.get("product_url"),
                    "sku": c.get("sku"),
                    "gtin": c.get("gtin") or c.get("ean") or c.get("gtin13"),
                }
                if sz == size:
                    out["accepted"].append(item)
                else:
                    reason = "missing_size" if sz is None else f"wrong_size:{sz}"
                    item["reject_reason"] = reason
                    out["rejected"].append(item)
            out["accepted_count"] = len(out["accepted"])
            out["accepted"] = out["accepted"][:10]
            out["rejected"] = out["rejected"][:20]
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            out["elapsed_ms"] = round((_diag_time.monotonic() - t0) * 1000)
        return out

    with _DiagPool(max_workers=2) as pool:
        fmap = {pool.submit(one, store, size): (store, size) for store, size in jobs}
        for fut in _diag_as_completed(fmap):
            store, size = fmap[fut]
            try:
                rows.append(fut.result())
            except Exception as exc:
                rows.append({"store": store, "requested_size_ml": size, "error": f"future:{type(exc).__name__}: {exc}"})
            if (_diag_time.monotonic() - started) > budget:
                # Do not cancel already-running work; report the fact that the
                # requested diagnostic budget was exceeded.
                break

    rows.sort(key=lambda x: (int(x.get("requested_size_ml") or 0), str(x.get("store") or "")))
    by_size = {}
    for row in rows:
        by_size.setdefault(str(row.get("requested_size_ml")), []).append(row)

    return {
        "ok": True,
        "diagnostic": "format_flow_read_only",
        "query": product,
        "requested_formats": sizes,
        "stores": FORMAT_STORES,
        "max_concurrency": 2,
        "budget_seconds": budget,
        "elapsed_total_ms": round((_diag_time.monotonic() - started) * 1000),
        "completed_jobs": len(rows),
        "expected_jobs": len(jobs),
        "budget_exceeded": (_diag_time.monotonic() - started) > budget,
        "by_format": by_size,
        "jobs": rows,
    }


# ===== READ-ONLY ALL-STORE DIAGNOSTIC =====
@app.get("/diagnose-all-stores")
def diagnose_all_stores(q: str = Query(..., min_length=1)):
    """Run the real 8-store SearchEngine diagnostic without changing search results."""
    return _engine.diagnostic_search(str(q).strip())

# ===== DEEP STORE SCRAPER DIAGNOSTIC (READ-ONLY) =====
# Purpose: expose the exact discovery/fetch/parse stage where a store loses a
# product. This endpoint does not modify normal search behaviour.
@app.get("/diagnostic-scraper-deep")
def diagnostic_scraper_deep(
    q: str = Query(..., min_length=1),
    store: str = Query(..., min_length=1),
):
    import importlib as _deep_importlib
    import time as _deep_time
    import requests as _deep_requests

    query = str(q or "").strip()
    store_key = str(store or "").strip().lower()
    allowed = {
        "deloox": "scrapers.deloox.scraper",
        "sabina": "scrapers.sabina.scraper",
    }
    if store_key not in allowed:
        return {
            "ok": False,
            "diagnostic": "scraper_deep_v1",
            "error": "unsupported_store",
            "allowed_stores": sorted(allowed),
        }

    started = _deep_time.monotonic()
    try:
        module = _deep_importlib.import_module(allowed[store_key])
    except Exception as exc:
        return {
            "ok": False,
            "diagnostic": "scraper_deep_v1",
            "store": store_key,
            "query": query,
            "stage": "module_load",
            "error": f"{type(exc).__name__}: {exc}",
        }

    # Module identity / provenance diagnostics.  This is deliberately collected
    # before any discovery call so that a stale/wrong Railway module cannot be
    # mistaken for a scraper discovery failure.
    module_file = str(getattr(module, "__file__", "") or "")
    module_spec = getattr(module, "__spec__", None)
    module_origin = str(getattr(module_spec, "origin", "") or "") if module_spec else ""
    module_source = ""
    module_source_sha256 = None
    module_source_lines = None
    module_source_error = None
    if module_file:
        try:
            _module_path = __import__("pathlib").Path(module_file)
            if _module_path.exists() and _module_path.is_file():
                module_source = _module_path.read_text(encoding="utf-8", errors="replace")
                module_source_sha256 = __import__("hashlib").sha256(
                    module_source.encode("utf-8", errors="replace")
                ).hexdigest()
                module_source_lines = len(module_source.splitlines())
        except Exception as _exc:
            module_source_error = f"{type(_exc).__name__}: {_exc}"

    base = str(getattr(module, "BASE_URL", ""))
    headers = dict(getattr(module, "HEADERS", {}) or {})
    timeout = getattr(module, "TIMEOUT", None)

    class _LoggedSession(_deep_requests.Session):
        def __init__(self):
            super().__init__()
            self.calls = []

        def get(self, url, **kwargs):
            t0 = _deep_time.monotonic()
            try:
                response = super().get(url, **kwargs)
                entry = {
                    "url": str(url),
                    "final_url": str(getattr(response, "url", "") or ""),
                    "status": response.status_code,
                    "bytes": len(response.content or b""),
                    "elapsed_ms": round((_deep_time.monotonic() - t0) * 1000),
                    "content_type": response.headers.get("content-type"),
                }
                self.calls.append(entry)
                return response
            except Exception as exc:
                self.calls.append({
                    "url": str(url),
                    "status": None,
                    "bytes": 0,
                    "elapsed_ms": round((_deep_time.monotonic() - t0) * 1000),
                    "error": f"{type(exc).__name__}: {exc}",
                })
                raise

    session = _LoggedSession()
    if headers:
        session.headers.update(headers)

    result = {
        "ok": True,
        "diagnostic": "scraper_deep_v1",
        "store": store_key,
        "query": query,
        "module": module.__name__,
        "base_url": base,
        "configured_timeout": timeout,
        "stages": {},
        "http_calls": session.calls,
    }

    try:
        if store_key == "deloox":
            # Run the exact discovery function used by search(), then manually
            # run its authoritative product parser on every discovered URL.
            t0 = _deep_time.monotonic()
            discover = getattr(module, "_discover", None)
            if not callable(discover):
                # Never hide the real cause behind a generic _discover_not_found.
                # Return the loaded module's provenance and available callables.
                available = sorted(
                    name for name in dir(module)
                    if name.startswith("_") and callable(getattr(module, name, None))
                )
                trace["stage"] = "module_introspection"
                trace["module_introspection"] = {
                    "module_file": module_file,
                    "module_origin": module_origin,
                    "module_source_sha256": module_source_sha256,
                    "module_source_lines": module_source_lines,
                    "required_functions_present": {
                        name: callable(getattr(module, name, None))
                        for name in [
                            "_discover",
                            "_discover_from_categories",
                            "_candidate_product_urls",
                            "_category_product_line_links",
                            "_find_catalog_filter_url",
                            "_sitemap_product_urls",
                            "_product",
                        ]
                    },
                    "available_private_callables": available[:300],
                }
                raise RuntimeError("_discover_not_found_in_loaded_module")
            urls = discover(session, query) or []
            result["stages"]["discovery"] = {
                "elapsed_ms": round((_deep_time.monotonic() - t0) * 1000),
                "candidate_url_count": len(urls),
                "candidate_urls": list(urls)[:30],
            }

            parsed = []
            rejected = []
            parser = getattr(module, "_product", None)
            if callable(parser):
                for url in list(urls)[:30]:
                    t1 = _deep_time.monotonic()
                    try:
                        r = session.get(url, headers=headers, timeout=timeout or 4)
                        status = r.status_code
                        body = r.text if status < 400 else ""
                        bytes_count = len(r.content or b"")
                        r.close()
                        if status >= 400:
                            rejected.append({"url": url, "reason": f"http_{status}", "bytes": bytes_count})
                            continue
                        item = parser(url, body, query)
                        if item is None:
                            rejected.append({
                                "url": url,
                                "reason": "parser_returned_none",
                                "bytes": bytes_count,
                                "html_contains_query": query.casefold() in body.casefold(),
                            })
                        else:
                            parsed.append({
                                "url": url,
                                "name": item.get("name"),
                                "size_ml": (item.get("attributes") or {}).get("size_ml"),
                                "price": item.get("price"),
                                "available": item.get("available"),
                                "gtin": (item.get("identity") or {}).get("gtin"),
                                "sku": (item.get("identity") or {}).get("sku"),
                            })
                    except Exception as exc:
                        rejected.append({"url": url, "reason": f"{type(exc).__name__}: {exc}"})
            result["stages"]["product_parse"] = {
                "parsed_count": len(parsed),
                "parsed": parsed[:30],
                "rejected_count": len(rejected),
                "rejected": rejected[:30],
            }

        else:
            # Sabina exposes sitemap discovery as a separate function. We run
            # it first, then execute the same _get + _parse_html sequence used
            # by search(), preserving the exact production parser.
            sitemap = getattr(module, "_sitemap_product_candidates", None)
            parser = getattr(module, "_parse_html", None)
            getter = getattr(module, "_get", None)
            if not callable(sitemap):
                raise RuntimeError("_sitemap_product_candidates_not_found")

            t0 = _deep_time.monotonic()
            urls = sitemap(session, query) or []
            result["stages"]["sitemap_discovery"] = {
                "elapsed_ms": round((_deep_time.monotonic() - t0) * 1000),
                "candidate_url_count": len(urls),
                "candidate_urls": list(urls)[:30],
            }

            parsed = []
            rejected = []
            if callable(parser):
                for url in list(urls)[:30]:
                    try:
                        if callable(getter):
                            r = getter(session, url)
                        else:
                            r = session.get(url, headers=headers, timeout=timeout or 4, allow_redirects=True)
                        if r is None:
                            rejected.append({"url": url, "reason": "getter_returned_none"})
                            continue
                        status = getattr(r, "status_code", None)
                        body = getattr(r, "text", "") or ""
                        bytes_count = len(getattr(r, "content", b"") or b"")
                        try:
                            r.close()
                        except Exception:
                            pass
                        if status is not None and status >= 400:
                            rejected.append({"url": url, "reason": f"http_{status}", "bytes": bytes_count})
                            continue
                        rows = parser(body, query) or []
                        if rows:
                            parsed.extend(rows[:30])
                        else:
                            rejected.append({
                                "url": url,
                                "reason": "parser_returned_zero",
                                "bytes": bytes_count,
                                "html_contains_query": query.casefold() in body.casefold(),
                            })
                    except Exception as exc:
                        rejected.append({"url": url, "reason": f"{type(exc).__name__}: {exc}"})

            compact = []
            for item in parsed[:30]:
                if not isinstance(item, dict):
                    continue
                compact.append({
                    "name": item.get("name"),
                    "brand": item.get("brand"),
                    "size_ml": item.get("size_ml"),
                    "size": item.get("size"),
                    "price": item.get("price"),
                    "in_stock": item.get("in_stock"),
                    "url": item.get("url") or item.get("product_url"),
                    "sku": item.get("sku"),
                    "gtin": item.get("gtin") or item.get("ean") or item.get("gtin13"),
                })
            result["stages"]["product_parse"] = {
                "parsed_count": len(parsed),
                "parsed": compact,
                "rejected_count": len(rejected),
                "rejected": rejected[:30],
            }

        result["http_calls"] = session.calls
        result["summary"] = {
            "http_call_count": len(session.calls),
            "successful_http_calls": sum(1 for x in session.calls if x.get("status") and x.get("status") < 400),
            "http_errors": sum(1 for x in session.calls if x.get("status") is None or x.get("status", 0) >= 400),
            "total_elapsed_ms": round((_deep_time.monotonic() - started) * 1000),
        }
        return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["summary"] = {
            "http_call_count": len(session.calls),
            "total_elapsed_ms": round((_deep_time.monotonic() - started) * 1000),
        }
        result["http_calls"] = session.calls
        return result
    finally:
        session.close()

# ===== FORENSIC SCRAPER TRACE V2 (READ-ONLY) =====
# This endpoint does NOT change scraper/search behaviour. It instruments the
# existing scraper functions in-memory for one request and reports exactly
# where a query/result disappears: HTTP -> raw HTML -> candidate extraction ->
# query matching -> product parser -> final candidate rows.
@app.get("/diagnostic-scraper-trace")
def diagnostic_scraper_trace(
    q: str = Query(..., min_length=1),
    store: str = Query(..., min_length=1),
):
    import importlib as _trace_importlib
    import time as _trace_time
    import traceback as _trace_tb
    import requests as _trace_requests

    query = str(q or "").strip()
    store_key = str(store or "").strip().lower()
    allowed = {
        "deloox": "scrapers.deloox.scraper",
        "sabina": "scrapers.sabina.scraper",
    }
    if store_key not in allowed:
        return {"ok": False, "diagnostic": "scraper_trace_v3_module_identity", "error": "unsupported_store", "allowed_stores": sorted(allowed)}

    started = _trace_time.monotonic()
    try:
        module = _trace_importlib.import_module(allowed[store_key])
    except Exception as exc:
        return {"ok": False, "diagnostic": "scraper_trace_v3_module_identity", "stage": "module_load", "error": f"{type(exc).__name__}: {exc}"}

    base = str(getattr(module, "BASE_URL", ""))
    headers = dict(getattr(module, "HEADERS", {}) or {})
    timeout = getattr(module, "TIMEOUT", None)

    class _TraceSession(_trace_requests.Session):
        def __init__(self):
            super().__init__()
            self.calls = []

        def get(self, url, **kwargs):
            t0 = _trace_time.monotonic()
            try:
                r = super().get(url, **kwargs)
                body = r.text or ""
                low = body.casefold()
                self.calls.append({
                    "url": str(url),
                    "final_url": str(getattr(r, "url", "") or ""),
                    "status": r.status_code,
                    "bytes": len(r.content or b""),
                    "elapsed_ms": round((_trace_time.monotonic() - t0) * 1000),
                    "content_type": r.headers.get("content-type"),
                    "query_found_raw_html": query.casefold() in low,
                    "query_token_hits": {tok: tok.casefold() in low for tok in _trace_re_tokens(query)},
                })
                return r
            except Exception as exc:
                self.calls.append({
                    "url": str(url), "status": None, "bytes": 0,
                    "elapsed_ms": round((_trace_time.monotonic() - t0) * 1000),
                    "error": f"{type(exc).__name__}: {exc}",
                })
                raise

    def _trace_re_tokens(text):
        return [x for x in re.findall(r"[a-z0-9]+", text.casefold()) if len(x) >= 3]

    def _short(v, n=500):
        s = re.sub(r"\s+", " ", str(v or "")).strip()
        return s[:n]

    def _restore(patches):
        for obj, name, original in reversed(patches):
            try:
                setattr(obj, name, original)
            except Exception:
                pass

    trace = {
        "ok": True,
        "diagnostic": "scraper_trace_v3_module_identity",
        "store": store_key,
        "query": query,
        "module": module.__name__,
        "module_file": module_file,
        "module_origin": module_origin,
        "module_source_sha256": module_source_sha256,
        "module_source_lines": module_source_lines,
        "module_source_error": module_source_error,
        "module_functions": {
            name: callable(getattr(module, name, None))
            for name in [
                "_discover",
                "_discover_from_categories",
                "_candidate_product_urls",
                "_category_product_line_links",
                "_find_catalog_filter_url",
                "_sitemap_product_urls",
                "_product",
                "search",
            ]
        },
        "module_constants": {
            "BASE_URL": base,
            "TIMEOUT": timeout,
        },
        "query_tokens": _trace_re_tokens(query),
        "stages": {},
        "http_calls": [],
        "function_trace": [],
    }
    session = _TraceSession()
    if headers:
        session.headers.update(headers)

    patches = []

    def _patch(obj, name, wrapper):
        original = getattr(obj, name, None)
        if callable(original):
            patches.append((obj, name, original))
            setattr(obj, name, wrapper(original))
            return original
        return None

    try:
        # ---- Deloox: instrument EVERY discovery sub-stage ----
        if store_key == "deloox":
            def wrap_candidate(original):
                def wrapped(html, query_arg=None):
                    before = _trace_time.monotonic()
                    result = original(html, query_arg)
                    urls = list(result or [])
                    query_low = str(query_arg or query).casefold()
                    # Independent evidence from the same HTML, without changing
                    # the production parser: all hrefs whose visible href/text
                    # contains at least one meaningful query token.
                    soup = BeautifulSoup(html or "", "html.parser")
                    evidence = []
                    toks = _trace_re_tokens(query_low)
                    for a in soup.find_all("a", href=True):
                        href = str(a.get("href") or "")
                        text = a.get_text(" ", strip=True)
                        hay = (href + " " + text).casefold()
                        hits = [t for t in toks if t in hay]
                        if hits:
                            evidence.append({"href": href[:500], "text": _short(text, 240), "token_hits": hits})
                    entry = {
                        "function": "_candidate_product_urls",
                        "input_html_bytes": len(html or ""),
                        "query": query_arg,
                        "production_output_count": len(urls),
                        "production_output": urls[:100],
                        "independent_token_evidence_count": len(evidence),
                        "independent_token_evidence": evidence[:100],
                        "elapsed_ms": round((_trace_time.monotonic() - before) * 1000),
                    }
                    trace["function_trace"].append(entry)
                    return result
                return wrapped
            _patch(module, "_candidate_product_urls", wrap_candidate)

            for fname in ["_category_product_line_links", "_find_catalog_filter_url", "_discover_from_categories", "_sitemap_product_urls"]:
                def make_wrap(name):
                    def factory(original):
                        def wrapped(*args, **kwargs):
                            t0 = _trace_time.monotonic()
                            try:
                                result = original(*args, **kwargs)
                                out = list(result or []) if isinstance(result, (list, tuple, set)) else result
                                trace["function_trace"].append({
                                    "function": name,
                                    "returned_type": type(result).__name__,
                                    "returned_count": len(out) if isinstance(out, (list, tuple, set)) else None,
                                    "returned": out[:100] if isinstance(out, list) else _short(out, 1000),
                                    "elapsed_ms": round((_trace_time.monotonic() - t0) * 1000),
                                })
                                return result
                            except Exception as exc:
                                trace["function_trace"].append({
                                    "function": name,
                                    "error": f"{type(exc).__name__}: {exc}",
                                    "traceback": _short(_trace_tb.format_exc(), 1200),
                                    "elapsed_ms": round((_trace_time.monotonic() - t0) * 1000),
                                })
                                raise
                        return wrapped
                    return factory
                _patch(module, fname, make_wrap(fname))

            discover = getattr(module, "_discover", None)
            if not callable(discover):
                raise RuntimeError("_discover_not_found")
            t0 = _trace_time.monotonic()
            urls = discover(session, query) or []
            trace["stages"]["discovery"] = {
                "elapsed_ms": round((_trace_time.monotonic() - t0) * 1000),
                "candidate_url_count": len(urls),
                "candidate_urls": list(urls)[:100],
            }

            # Now trace the exact parser decision for every discovered URL.
            parser = getattr(module, "_product", None)
            parsed, rejected = [], []
            if callable(parser):
                for url in list(urls)[:50]:
                    try:
                        r = session.get(url, headers=headers, timeout=timeout or 4)
                        body = r.text or ""
                        status = r.status_code
                        if status >= 400:
                            rejected.append({"url": url, "stage": "product_http", "reason": f"http_{status}"})
                            continue
                        item = parser(url, body, query)
                        if item is None:
                            rejected.append({
                                "url": url,
                                "stage": "product_parser",
                                "reason": "parser_returned_none",
                                "html_contains_query": query.casefold() in body.casefold(),
                                "query_token_hits": {tok: tok.casefold() in body.casefold() for tok in _trace_re_tokens(query)},
                            })
                        else:
                            parsed.append({"url": url, "item": item})
                    except Exception as exc:
                        rejected.append({"url": url, "stage": "product_parser_exception", "reason": f"{type(exc).__name__}: {exc}"})
            trace["stages"]["product_parse"] = {
                "parsed_count": len(parsed),
                "parsed": parsed[:30],
                "rejected_count": len(rejected),
                "rejected": rejected[:50],
            }

        # ---- Sabina: instrument sitemap XML and HTML parser boundaries ----
        else:
            def wrap_xml(original):
                def wrapped(text):
                    result = original(text)
                    locs = list(result or [])
                    toks = _trace_re_tokens(query)
                    matching = [u for u in locs if any(t in str(u).casefold() for t in toks)]
                    trace["function_trace"].append({
                        "function": "_xml_locs",
                        "input_bytes": len(text or ""),
                        "loc_count": len(locs),
                        "query_token_matching_loc_count": len(matching),
                        "query_token_matching_locs": matching[:100],
                        "sample_locs": locs[:30],
                    })
                    return result
                return wrapped
            _patch(module, "_xml_locs", wrap_xml)

            for fname in ["_extract_variants_from_html", "_parse_html", "_enrich_product_sizes", "_dedupe"]:
                def make_sab_wrap(name):
                    def factory(original):
                        def wrapped(*args, **kwargs):
                            t0 = _trace_time.monotonic()
                            try:
                                result = original(*args, **kwargs)
                                if isinstance(result, (list, tuple, set)):
                                    compact = list(result)
                                    trace["function_trace"].append({
                                        "function": name,
                                        "returned_count": len(compact),
                                        "returned_sample": compact[:20],
                                        "elapsed_ms": round((_trace_time.monotonic() - t0) * 1000),
                                    })
                                else:
                                    trace["function_trace"].append({
                                        "function": name,
                                        "returned_type": type(result).__name__,
                                        "returned": result,
                                        "elapsed_ms": round((_trace_time.monotonic() - t0) * 1000),
                                    })
                                return result
                            except Exception as exc:
                                trace["function_trace"].append({"function": name, "error": f"{type(exc).__name__}: {exc}", "traceback": _short(_trace_tb.format_exc(), 1200)})
                                raise
                        return wrapped
                    return factory
                _patch(module, fname, make_sab_wrap(fname))

            sitemap = getattr(module, "_sitemap_product_candidates", None)
            if not callable(sitemap):
                raise RuntimeError("_sitemap_product_candidates_not_found")
            t0 = _trace_time.monotonic()
            urls = sitemap(session, query) or []
            trace["stages"]["sitemap_discovery"] = {
                "elapsed_ms": round((_trace_time.monotonic() - t0) * 1000),
                "candidate_url_count": len(urls),
                "candidate_urls": list(urls)[:100],
            }

            parser = getattr(module, "_parse_html", None)
            getter = getattr(module, "_get", None)
            parsed, rejected = [], []
            if callable(parser):
                for url in list(urls)[:50]:
                    try:
                        r = getter(session, url) if callable(getter) else session.get(url, headers=headers, timeout=timeout or 3, allow_redirects=True)
                        if r is None:
                            rejected.append({"url": url, "stage": "product_http", "reason": "getter_returned_none"})
                            continue
                        body = getattr(r, "text", "") or ""
                        status = getattr(r, "status_code", None)
                        if status is not None and status >= 400:
                            rejected.append({"url": url, "stage": "product_http", "reason": f"http_{status}"})
                            continue
                        rows = parser(body, query) or []
                        if rows:
                            parsed.extend(rows[:50])
                        else:
                            rejected.append({
                                "url": url,
                                "stage": "product_parser",
                                "reason": "parser_returned_zero",
                                "html_contains_query": query.casefold() in body.casefold(),
                                "query_token_hits": {tok: tok.casefold() in body.casefold() for tok in _trace_re_tokens(query)},
                            })
                    except Exception as exc:
                        rejected.append({"url": url, "stage": "product_parser_exception", "reason": f"{type(exc).__name__}: {exc}"})

            trace["stages"]["product_parse"] = {
                "parsed_count": len(parsed),
                "parsed": parsed[:50],
                "rejected_count": len(rejected),
                "rejected": rejected[:50],
            }

        trace["http_calls"] = session.calls
        trace["summary"] = {
            "http_call_count": len(session.calls),
            "successful_http_calls": sum(1 for x in session.calls if x.get("status") and x.get("status") < 400),
            "http_errors": sum(1 for x in session.calls if x.get("status") is None or x.get("status", 0) >= 400),
            "total_elapsed_ms": round((_trace_time.monotonic() - started) * 1000),
        }
        return trace
    except Exception as exc:
        trace["error"] = f"{type(exc).__name__}: {exc}"
        trace["traceback"] = _short(_trace_tb.format_exc(), 2000)
        trace["http_calls"] = session.calls
        trace["summary"] = {"http_call_count": len(session.calls), "total_elapsed_ms": round((_trace_time.monotonic() - started) * 1000)}
        return trace
    finally:
        _restore(patches)
        try:
            session.close()
        except Exception:
            pass
