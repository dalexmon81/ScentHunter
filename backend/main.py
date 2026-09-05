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
    """Resolve the candidate's real package size with conflict protection.

    A scraper may expose a stale/inherited size_ml while the actual product
    title/URL contains another explicit size. Text attached to the concrete
    offer is authoritative when it contains exactly one package size.
    Conflicting textual sizes are treated as unknown unless the explicit
    structured size agrees with one of them.
    """
    candidate = candidate or {}

    explicit = None
    for key in ("size_ml", "volume_ml", "format_ml"):
        value = candidate.get(key)
        if value in (None, ""):
            continue
        try:
            explicit = float(str(value).replace(",", "."))
            break
        except (TypeError, ValueError):
            continue

    text_parts = []
    for key in (
        "name", "title", "product_name", "size", "format", "volume",
        "url", "product_url",
    ):
        value = candidate.get(key)
        if value not in (None, ""):
            text_parts.append(str(value))

    source = candidate.get("source")
    if isinstance(source, dict):
        for key in ("name", "title", "url", "product_url"):
            value = source.get(key)
            if value not in (None, ""):
                text_parts.append(str(value))

    raw_data = candidate.get("raw_data")
    if isinstance(raw_data, dict):
        for key in ("name", "title", "product_title", "size", "format", "volume", "url", "product_url"):
            value = raw_data.get(key)
            if value not in (None, ""):
                text_parts.append(str(value))

    text_sizes = []
    pattern = re.compile(r"\b(\d{1,4}(?:[.,]\d+)?)\s*(ml|cl|dl|l)\b", re.I)
    for text in text_parts:
        for match in pattern.finditer(text):
            try:
                number = float(match.group(1).replace(",", "."))
            except (TypeError, ValueError):
                continue
            unit = match.group(2).lower()
            if unit == "cl":
                number *= 10
            elif unit == "dl":
                number *= 100
            elif unit == "l":
                number *= 1000
            text_sizes.append(number)

    unique_text_sizes = sorted({round(x, 4) for x in text_sizes})

    if len(unique_text_sizes) == 1:
        return int(unique_text_sizes[0]) if unique_text_sizes[0].is_integer() else int(round(unique_text_sizes[0]))

    if len(unique_text_sizes) > 1:
        if explicit is not None:
            for value in unique_text_sizes:
                if abs(value - explicit) <= 0.01:
                    return int(value) if value.is_integer() else int(round(value))
        return None

    if explicit is not None:
        return int(explicit) if explicit.is_integer() else int(round(explicit))

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
    """Build the store discovery query.

    Format comparison uses generic product discovery; the requested size is
    validated later from explicit parsed product data.
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
    """Search one store and accept only the exact requested parsed format.

    Discovery is generic so store-level query filters cannot discard a valid
    product merely because its size is absent from the searchable title.
    Acceptance still requires an explicit parsed size equal to requested_size.
    """
    # Discovery must stay generic. The requested format is validated only
    # after the scraper returns explicit product size data.
    query = _format_compare_query(product, None)

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

def _format_compare_store_all(
    store: str,
    product: str,
    requested_sizes: List[int],
) -> Dict[str, Any]:
    """Discover one store once and classify every returned variant by size."""
    try:
        raw = _legacy.run_store(store, _format_compare_query(product, None))
    except Exception as exc:
        return {
            "store": store,
            "results": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    candidates = raw if isinstance(raw, list) else []
    normalized = []
    wanted = set(requested_sizes)

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        item = dict(candidate)
        size = _format_compare_size(item)
        if size is None or size not in wanted:
            continue
        item["size_ml"] = size
        item["size_source"] = item.get("size_source", "central_format_parser")
        normalized.append(item)

    try:
        validated = _engine._validate_candidates_only(product, normalized)
    except Exception:
        validated = normalized

    cleaned = []
    for candidate in validated or []:
        if not isinstance(candidate, dict):
            continue
        size = _format_compare_size(candidate)
        if size is None or size not in wanted:
            continue
        item = dict(candidate)
        item["size_ml"] = size
        try:
            cleaned.append(_format_compare_clean_offer(item, store, size))
        except ValueError:
            continue

    cleaned.sort(key=lambda offer: (
        _format_compare_is_oos(offer),
        _format_compare_num(offer.get("price_value")),
    ))

    return {"store": store, "results": cleaned}

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

    # One discovery per store, then classify all requested formats from the
    # returned concrete candidates. The old implementation performed
    # 8 stores x N formats searches, which created the ~1 minute delay and
    # multiplied rate-limit pressure without adding validation value.
    jobs = list(FORMAT_STORES)

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_map = {
            pool.submit(
                _format_compare_store_all,
                store,
                product,
                requested_sizes,
            ): store
            for store in jobs
        }

        for future in as_completed(future_map):
            store = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                errors[store] = f"{type(exc).__name__}: {exc}"
                continue
            if result.get("error"):
                errors[store] = result["error"]
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

# ===== READ-ONLY FORMAT TRACE DIAGNOSTIC =====
# Deep trace of ONE exact store/format call. This does not alter any live route.
# It is intentionally sequential: the goal is attribution, not throughput.
@app.get("/diagnose-format-trace")
def diagnose_format_trace(
    q: str = Query(..., min_length=1),
    size: int = Query(..., ge=1, le=2000),
    store: str = Query(..., min_length=1),
):
    product = str(q or "").strip()
    store_name = str(store or "").strip().casefold()
    requested_size = int(size)
    # Diagnostic must reproduce production discovery: generic query first,
    # then explicit size validation after scraper return.
    query = _format_compare_query(product, None)
    exact_query = _format_compare_query(product, requested_size)
    started = _diag_time.monotonic()

    def candidate_snapshot(c: Any) -> Dict[str, Any]:
        if not isinstance(c, dict):
            return {
                "type": type(c).__name__,
                "value": str(c)[:2000],
            }

        snap = {}
        # Preserve every field relevant to discovery, matching, size,
        # availability and navigation. No price or field is invented.
        for key in (
            "name", "brand", "title", "size_ml", "size", "format",
            "volume", "quantity", "price", "price_value", "currency",
            "in_stock", "availability", "stock", "status",
            "url", "product_url", "link", "sku", "ean", "gtin", "gtin13",
            "store", "image", "source", "size_source",
        ):
            if key in c:
                value = c.get(key)
                if isinstance(value, (str, int, float, bool)) or value is None:
                    snap[key] = value
                else:
                    snap[key] = str(value)[:2000]
        return snap

    trace = {
        "ok": True,
        "diagnostic": "format_trace_read_only_v1",
        "query": product,
        "requested_size_ml": requested_size,
        "store": store_name,
        "discovery_query": query,
        "exact_query_reference": exact_query,
        "timings_ms": {},
        "stages": {},
        "final": [],
        "error": None,
    }

    try:
        t0 = _diag_time.monotonic()
        raw = _legacy.run_store(store_name, query)
        trace["timings_ms"]["run_store"] = round((_diag_time.monotonic() - t0) * 1000)

        candidates = raw if isinstance(raw, list) else []
        trace["stages"]["raw"] = {
            "type": type(raw).__name__,
            "count": len(candidates),
            "candidates": [candidate_snapshot(c) for c in candidates[:50]],
            "truncated": len(candidates) > 50,
        }

        # Measure the central size extractor BEFORE any format filtering.
        t0 = _diag_time.monotonic()
        raw_size_analysis = []
        for idx, candidate in enumerate(candidates[:50]):
            if not isinstance(candidate, dict):
                raw_size_analysis.append({
                    "index": idx,
                    "parsed_size_ml": None,
                    "reason": "non_dict_candidate",
                    "candidate": candidate_snapshot(candidate),
                })
                continue
            parsed = _format_compare_size(candidate)
            raw_size_analysis.append({
                "index": idx,
                "parsed_size_ml": parsed,
                "matches_requested_size": parsed == requested_size,
                "reason": (
                    "accepted_for_size"
                    if parsed == requested_size
                    else ("missing_size" if parsed is None else f"wrong_size:{parsed}")
                ),
                "candidate": candidate_snapshot(candidate),
            })
        trace["timings_ms"]["size_extraction_raw"] = round(
            (_diag_time.monotonic() - t0) * 1000
        )
        trace["stages"]["size_extraction_before_validation"] = {
            "requested_size_ml": requested_size,
            "items": raw_size_analysis,
        }

        # This reproduces the exact pre-validation filtering used by
        # /compare-formats, so we can see whether the loss happens here.
        size_filtered = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            parsed = _format_compare_size(candidate)
            if parsed is None or parsed != requested_size:
                continue
            item = dict(candidate)
            item["size_ml"] = parsed
            item["size_source"] = item.get(
                "size_source",
                "central_product_size_ml",
            )
            size_filtered.append(item)

        trace["stages"]["after_exact_size_filter"] = {
            "count": len(size_filtered),
            "candidates": [candidate_snapshot(c) for c in size_filtered[:50]],
            "dropped_count": max(0, len(candidates) - len(size_filtered)),
        }

        # Run the same central validator as /compare-formats.
        t0 = _diag_time.monotonic()
        try:
            validated = _engine._validate_candidates_only(
                product,
                size_filtered,
            )
            validation_error = None
        except Exception as exc:
            validation_error = f"{type(exc).__name__}: {exc}"
            validated = size_filtered
        trace["timings_ms"]["central_validation"] = round(
            (_diag_time.monotonic() - t0) * 1000
        )
        validated = validated or []

        trace["stages"]["after_central_validation"] = {
            "count": len(validated),
            "validation_error": validation_error,
            "candidates": [candidate_snapshot(c) for c in validated[:50]],
            "dropped_count": max(0, len(size_filtered) - len(validated)),
        }

        # Final cleaning is also reproduced exactly.
        cleaned = []
        clean_rejected = []
        for candidate in validated:
            if not isinstance(candidate, dict):
                clean_rejected.append({
                    "reason": "non_dict_after_validation",
                    "candidate": candidate_snapshot(candidate),
                })
                continue

            explicit_size = _format_compare_size(candidate)
            if explicit_size != requested_size:
                clean_rejected.append({
                    "reason": (
                        "missing_size"
                        if explicit_size is None
                        else f"wrong_size:{explicit_size}"
                    ),
                    "candidate": candidate_snapshot(candidate),
                })
                continue

            item = dict(candidate)
            item["size_ml"] = explicit_size
            try:
                cleaned.append(
                    _format_compare_clean_offer(
                        item,
                        store_name,
                        requested_size,
                    )
                )
            except Exception as exc:
                clean_rejected.append({
                    "reason": f"{type(exc).__name__}: {exc}",
                    "candidate": candidate_snapshot(candidate),
                })

        trace["stages"]["final_cleaning"] = {
            "count": len(cleaned),
            "rejected_count": len(clean_rejected),
            "rejected": clean_rejected[:50],
            "candidates": [candidate_snapshot(c) for c in cleaned[:50]],
        }
        trace["final"] = cleaned[:50]

    except Exception as exc:
        trace["error"] = f"{type(exc).__name__}: {exc}"

    trace["timings_ms"]["total"] = round(
        (_diag_time.monotonic() - started) * 1000
    )
    return trace

