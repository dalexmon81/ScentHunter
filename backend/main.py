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

    offer["in_stock"] = not _format_compare_is_oos(offer)
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

        # IMPORTANT: format diagnosis must use the same broad discovery query
        # as production. The requested size is enforced after scraping from
        # the candidate's explicit parsed size. Putting "100 ml" into the
        # retailer query makes several adapters return zero results.
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
                    "size_ml": c.get("size_ml"),
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
