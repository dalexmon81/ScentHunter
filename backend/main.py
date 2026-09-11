"""
ScentHunter - STABLE LIVE SEARCH BACKEND

Ricerca reale su 8 store, eseguita SEQUENZIALMENTE per evitare
OOM/contesa RAM su Render.

Non modifica gli scraper.
ProductMatcher resta il livello centrale di identità prodotto.
"""

from __future__ import annotations

import copy
import gc
import importlib
import json
import logging
import re
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from product_matcher import ProductMatcher


# ============================================================================
# APP
# ============================================================================

app = FastAPI(
    title="ScentHunter API",
    version="3.1-stable-sequential",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# CONFIG
# ============================================================================

STORES = [
    "bplatz",
    "deloox",
    "parfumcity",
    "parfumzentrum",
    "perfumemarket",
    "sabina",
    "orioudh",
    "notino",
]

STORE_LABELS = {
    "bplatz": "Bplatz",
    "deloox": "Deloox",
    "parfumcity": "ParfumCity",
    "parfumzentrum": "ParfumZentrum",
    "perfumemarket": "PerfumeMarket",
    "sabina": "Sabina",
    "orioudh": "Orioudh",
    "notino": "Notino",
}

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_INDEX = BASE_DIR.parent / "frontend" / "index.html"

# Cache breve solo per risultati NON vuoti.
CACHE_TTL_SECONDS = 90.0
MAX_RESULTS_PER_STORE = 80
MAX_OFFERS_PER_COMPARISON = 100

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | ScentHunter | %(message)s",
)
logger = logging.getLogger("scent-hunter")

_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()

_MATCHER: Optional[ProductMatcher] = None
_MATCHER_LOCK = threading.Lock()

JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
MAX_JOBS = 40


# ============================================================================
# TEXT / NUMERI
# ============================================================================

def _norm_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    return text


def _safe_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    text = str(value).strip().replace("\xa0", " ").replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", text)

    if not match:
        return None

    try:
        return float(match.group(0))
    except (TypeError, ValueError):
        return None


def _parse_size_ml(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        number = float(value)
        return number if number > 0 else None

    text = str(value).strip().lower().replace(",", ".")

    ml_match = re.search(
        r"(?<!\d)(\d+(?:\.\d+)?)\s*ml\b",
        text,
    )
    if ml_match:
        return float(ml_match.group(1))

    cl_match = re.search(
        r"(?<!\d)(\d+(?:\.\d+)?)\s*cl\b",
        text,
    )
    if cl_match:
        return float(cl_match.group(1)) * 10.0

    return None


def _normalise_store(value: Any, fallback: str) -> str:
    text = _norm_text(value or fallback)

    aliases = {
        "bplatz": "bplatz",
        "bplatz.de": "bplatz",
        "deloox": "deloox",
        "deloox.be": "deloox",
        "parfumcity": "parfumcity",
        "parfum city": "parfumcity",
        "parfumzentrum": "parfumzentrum",
        "parfum zentrum": "parfumzentrum",
        "parfum-zentrum": "parfumzentrum",
        "perfumemarket": "perfumemarket",
        "perfume market": "perfumemarket",
        "sabina": "sabina",
        "orioudh": "orioudh",
        "orioudh.com": "orioudh",
        "notino": "notino",
        "notino.fr": "notino",
    }

    return aliases.get(text, text)


# ============================================================================
# CACHE
# ============================================================================

def _cache_key(store: str, query: str) -> Tuple[str, str]:
    return (
        str(store).strip().lower(),
        _norm_text(query),
    )


def _cache_get(
    store: str,
    query: str,
) -> Optional[List[Dict[str, Any]]]:
    with _CACHE_LOCK:
        entry = _CACHE.get(_cache_key(store, query))

        if not entry:
            return None

        age = time.monotonic() - float(entry.get("saved_at", 0.0))

        if age <= CACHE_TTL_SECONDS:
            return copy.deepcopy(entry.get("results", []))

        _CACHE.pop(_cache_key(store, query), None)
        return None


def _cache_put(
    store: str,
    query: str,
    results: List[Dict[str, Any]],
) -> None:
    # MAI memorizzare una risposta vuota:
    # un errore/transitorio non deve diventare "nessun prodotto".
    if not results:
        return

    with _CACHE_LOCK:
        _CACHE[_cache_key(store, query)] = {
            "saved_at": time.monotonic(),
            "results": copy.deepcopy(results),
        }


def _cache_clear() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


# ============================================================================
# MATCHER
# ============================================================================

def load_matcher() -> ProductMatcher:
    global _MATCHER

    if _MATCHER is not None:
        return _MATCHER

    with _MATCHER_LOCK:
        if _MATCHER is not None:
            return _MATCHER

        catalog_path = BASE_DIR / "product_catalog.json"
        family_path = BASE_DIR / "family_registry.json"

        catalog_payload = json.loads(
            catalog_path.read_text(encoding="utf-8")
        )
        family_payload = json.loads(
            family_path.read_text(encoding="utf-8")
        )

        products = (
            catalog_payload.get("products", [])
            if isinstance(catalog_payload, dict)
            else catalog_payload
        )
        families = (
            family_payload.get("families", [])
            if isinstance(family_payload, dict)
            else family_payload
        )

        if not isinstance(products, list):
            products = []

        if not isinstance(families, list):
            families = []

        _MATCHER = ProductMatcher(
            catalog=products,
            family_registry=families,
        )

        logger.info(
            "MATCHER READY | catalog=%s | families=%s",
            len(products),
            len(families),
        )

        return _MATCHER


def match_results(
    rows: List[Dict[str, Any]],
    query: str,
) -> List[Dict[str, Any]]:
    matcher = load_matcher()
    output: List[Dict[str, Any]] = []

    for row in rows:
        try:
            matched = matcher.match(row)
        except Exception as exc:
            logger.warning(
                "MATCH ERROR | store=%s | query=%r | %s",
                row.get("store"),
                query,
                exc,
            )
            continue

        if matched is not None:
            output.append(matched)

    return output


# ============================================================================
# TRASPORTO
# ============================================================================

def _coerce_rows(raw: Any) -> List[Dict[str, Any]]:
    if raw is None:
        return []

    if isinstance(raw, dict):
        for key in ("results", "items", "products", "offers"):
            value = raw.get(key)
            if isinstance(value, (list, tuple)):
                raw = value
                break
        else:
            return [dict(raw)]

    if isinstance(raw, (list, tuple)):
        iterable: Iterable[Any] = raw
    else:
        try:
            iterable = list(raw)
        except TypeError:
            return []

    return [
        dict(item)
        for item in iterable
        if isinstance(item, dict)
    ]


def clean_result(
    item: Dict[str, Any],
    store: str,
) -> Dict[str, Any]:
    result = dict(item)

    machine_store = _normalise_store(
        result.get("store") or result.get("shop"),
        store,
    )

    result["store"] = machine_store
    result["shop"] = STORE_LABELS.get(
        machine_store,
        str(result.get("shop") or machine_store),
    )

    if not result.get("name"):
        for key in (
            "title",
            "product_name",
            "productTitle",
        ):
            if result.get(key):
                result["name"] = str(result[key]).strip()
                break

    if result.get("brand") is not None:
        result["brand"] = str(result["brand"]).strip()

    if result.get("name") is not None:
        result["name"] = str(result["name"]).strip()

    if result.get("size_ml") in (None, ""):
        for key in (
            "volume_ml",
            "format_ml",
            "size_ml",
            "size",
            "volume",
            "format",
        ):
            parsed = _parse_size_ml(result.get(key))
            if parsed is not None:
                result["size_ml"] = parsed
                break

    if result.get("size_ml") is not None:
        try:
            result["size_ml"] = float(result["size_ml"])
        except (TypeError, ValueError):
            result["size_ml"] = None

    if result.get("price_num") in (None, ""):
        for key in (
            "price",
            "current_price",
            "sale_price",
        ):
            parsed = _safe_float(result.get(key))
            if parsed is not None:
                result["price_num"] = parsed
                break
    else:
        result["price_num"] = _safe_float(
            result.get("price_num")
        )

    if "available" in result:
        value = result.get("available")

        if isinstance(value, str):
            low = _norm_text(value)

            if low in {
                "true",
                "1",
                "yes",
                "available",
                "in stock",
            }:
                result["available"] = True
            elif low in {
                "false",
                "0",
                "no",
                "unavailable",
                "out of stock",
            }:
                result["available"] = False
            else:
                result["available"] = None
        elif value is None:
            result["available"] = None
        else:
            result["available"] = bool(value)

    elif "in_stock" in result:
        value = result.get("in_stock")

        if isinstance(value, str):
            low = _norm_text(value)

            if low in {
                "true",
                "1",
                "yes",
                "available",
                "in stock",
            }:
                result["available"] = True
            elif low in {
                "false",
                "0",
                "no",
                "unavailable",
                "out of stock",
            }:
                result["available"] = False
            else:
                result["available"] = None
        elif value is None:
            result["available"] = None
        else:
            result["available"] = bool(value)

    else:
        result["available"] = None

    if not result.get("url"):
        for key in (
            "product_url",
            "link",
            "href",
        ):
            if result.get(key):
                result["url"] = str(result[key]).strip()
                break

    if not result.get("image"):
        for key in (
            "image_url",
            "thumbnail",
            "image",
        ):
            if result.get(key):
                result["image"] = str(result[key]).strip()
                break

    return result


def result_key(
    item: Dict[str, Any],
) -> Tuple[str, str, str, str]:
    store = _normalise_store(
        item.get("store") or item.get("shop"),
        "",
    )

    product_id = str(
        item.get("store_product_id")
        or item.get("product_id")
        or item.get("sku")
        or item.get("mpn")
        or ""
    ).strip().lower()

    url = str(
        item.get("url")
        or item.get("product_url")
        or ""
    ).strip().lower()

    name = _norm_text(
        item.get("name")
        or item.get("title")
        or ""
    )

    brand = _norm_text(
        item.get("brand") or ""
    )

    size = item.get("size_ml")

    try:
        size_key = (
            f"{float(size):.3f}"
            if size is not None
            else ""
        )
    except (TypeError, ValueError):
        size_key = ""

    stable = url or product_id or f"{brand}|{name}"

    return (
        store,
        stable,
        size_key,
        _norm_text(
            item.get("variant")
            or item.get("concentration")
            or ""
        ),
    )


def dedupe_results(
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    seen = set()
    output: List[Dict[str, Any]] = []

    for item in results:
        key = result_key(item)

        if key in seen:
            continue

        seen.add(key)
        output.append(item)

    return output


def _stock_rank(
    item: Dict[str, Any],
) -> int:
    available = item.get("available")
    price = _safe_float(item.get("price_num"))

    if available is True and price is not None:
        return 0

    if available is True:
        return 1

    if available is None and price is not None:
        return 2

    if available is None:
        return 3

    return 4


def sort_results(
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    def key(item: Dict[str, Any]):
        price = _safe_float(item.get("price_num"))
        size = _safe_float(item.get("size_ml"))

        return (
            _stock_rank(item),
            price if price is not None else float("inf"),
            size if size is not None else float("inf"),
            _norm_text(item.get("shop")),
            _norm_text(item.get("name")),
        )

    return sorted(results, key=key)


# ============================================================================
# COMPARISONS
# ============================================================================

def _comparison_identity(
    item: Dict[str, Any],
) -> Tuple[str, str, str]:
    brand = str(
        item.get("canonical_brand")
        or item.get("brand")
        or ""
    ).strip()

    name = str(
        item.get("canonical_name")
        or item.get("name")
        or item.get("title")
        or ""
    ).strip()

    concentration = str(
        item.get("canonical_concentration")
        or item.get("concentration")
        or item.get("type")
        or ""
    ).strip()

    return (
        _norm_text(brand),
        _norm_text(name),
        _norm_text(concentration),
    )


def build_comparisons(
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    groups: Dict[
        Tuple[str, str, str],
        List[Dict[str, Any]],
    ] = {}

    for item in results:
        brand, name, concentration = _comparison_identity(
            item
        )

        if not name:
            continue

        groups.setdefault(
            (brand, name, concentration),
            [],
        ).append(item)

    comparisons: List[Dict[str, Any]] = []

    for offers in groups.values():
        offers = sort_results(
            dedupe_results(offers)
        )

        if not offers:
            continue

        first = offers[0]

        brand = str(
            first.get("canonical_brand")
            or first.get("brand")
            or ""
        ).strip()

        name = str(
            first.get("canonical_name")
            or first.get("name")
            or first.get("title")
            or ""
        ).strip()

        concentration = str(
            first.get("canonical_concentration")
            or first.get("concentration")
            or ""
        ).strip()

        formats = sorted(
            {
                round(float(item["size_ml"]), 3)
                for item in offers
                if item.get("size_ml") is not None
                and _safe_float(item.get("size_ml")) is not None
            }
        )

        comparisons.append(
            {
                "brand": brand,
                "name": name,
                "canonical_brand": str(
                    first.get("canonical_brand")
                    or brand
                ).strip(),
                "canonical_name": str(
                    first.get("canonical_name")
                    or name
                ).strip(),
                "concentration": concentration,
                "formats": formats,
                "offers": offers[
                    :MAX_OFFERS_PER_COMPARISON
                ],
                "count": len(offers),
            }
        )

    def comparison_key(
        group: Dict[str, Any],
    ):
        best_price = float("inf")

        for offer in group.get("offers", []):
            if offer.get("available") is False:
                continue

            price = _safe_float(
                offer.get("price_num")
            )

            if price is not None:
                best_price = min(
                    best_price,
                    price,
                )

        return (
            best_price,
            _norm_text(group.get("brand")),
            _norm_text(group.get("name")),
        )

    comparisons.sort(key=comparison_key)
    return comparisons


# ============================================================================
# SCRAPER
# ============================================================================

def load_scraper(store: str):
    return importlib.import_module(
        f"scrapers.{store}.scraper"
    )


def run_store(
    store: str,
    query: str,
    use_cache: bool = True,
) -> Dict[str, Any]:
    started = time.monotonic()
    query = str(query or "").strip()

    if use_cache:
        cached = _cache_get(store, query)

        if cached is not None:
            return {
                "store": store,
                "status": "cache",
                "cache": "fresh",
                "elapsed": round(
                    time.monotonic() - started,
                    3,
                ),
                "count": len(cached),
                "results": cached,
                "error": None,
            }

    module_name = f"scrapers.{store}.scraper"

    try:
        module = load_scraper(store)

        search = getattr(module, "search", None)

        if not callable(search):
            raise RuntimeError(
                f"scraper {store} non espone search(query)"
            )

        logger.info(
            "STORE START | %s | query=%r",
            store,
            query,
        )

        raw = search(query)
        rows = _coerce_rows(raw)

        cleaned = [
            clean_result(row, store)
            for row in rows[:MAX_RESULTS_PER_STORE]
        ]

        cleaned = dedupe_results(cleaned)

        matched = match_results(
            cleaned,
            query,
        )

        matched = dedupe_results(matched)
        matched = sort_results(matched)

        # Solo risultati reali NON vuoti entrano in cache.
        _cache_put(
            store,
            query,
            matched,
        )

        elapsed = round(
            time.monotonic() - started,
            3,
        )

        logger.info(
            "STORE END | %s | results=%s | elapsed=%ss",
            store,
            len(matched),
            elapsed,
        )

        return {
            "store": store,
            "status": "ok" if matched else "empty",
            "cache": "miss",
            "elapsed": elapsed,
            "count": len(matched),
            "results": matched,
            "error": None,
        }

    except Exception as exc:
        error_text = (
            f"{type(exc).__name__}: {exc}"
        )

        logger.exception(
            "STORE ERROR | %s | query=%r | %s",
            store,
            query,
            error_text,
        )

        return {
            "store": store,
            "status": "error",
            "cache": "miss",
            "elapsed": round(
                time.monotonic() - started,
                3,
            ),
            "count": 0,
            "results": [],
            "error": error_text,
        }

    finally:
        # Il punto fondamentale della versione stabile:
        # dopo ogni negozio liberiamo gli oggetti pesanti.
        try:
            sys.modules.pop(
                module_name,
                None,
            )
        except Exception:
            pass

        gc.collect()


# ============================================================================
# RICERCA GLOBALE SEQUENZIALE
# ============================================================================

def run_search(
    query: str,
    use_cache: bool = True,
) -> Dict[str, Any]:
    query = str(query or "").strip()
    started = time.monotonic()

    reports: List[Dict[str, Any]] = []
    all_results: List[Dict[str, Any]] = []

    # SEQUENZIALE VOLUTO.
    # Non cambiare in ThreadPoolExecutor:
    # i nostri scraper possono usare molta RAM contemporaneamente.
    for store in STORES:
        report = run_store(
            store,
            query,
            use_cache=use_cache,
        )

        reports.append(report)
        all_results.extend(
            report.get("results", [])
        )

        # Memoria liberata dopo OGNI store.
        gc.collect()

    all_results = sort_results(
        dedupe_results(all_results)
    )

    comparisons = build_comparisons(
        all_results
    )

    errors = {
        report["store"]: report["error"]
        for report in reports
        if report.get("error")
    }

    return {
        "query": query,
        "count": len(all_results),
        "results": all_results,
        "comparisons": comparisons,
        "errors": errors,
        "stores": {
            report["store"]: {
                "status": report["status"],
                "cache": report.get("cache"),
                "count": report["count"],
                "elapsed": report["elapsed"],
            }
            for report in reports
        },
        "completed_stores": len(reports),
        "total_stores": len(STORES),
        "partial": False,
        "elapsed": round(
            time.monotonic() - started,
            3,
        ),
    }


# ============================================================================
# JOB ASINCRONO
# ============================================================================

def _cleanup_jobs() -> None:
    with JOBS_LOCK:
        if len(JOBS) <= MAX_JOBS:
            return

        ordered = sorted(
            JOBS.items(),
            key=lambda pair: pair[1].get(
                "started_at",
                0.0,
            ),
        )

        for job_id, _ in ordered[
            : len(JOBS) - MAX_JOBS
        ]:
            JOBS.pop(job_id, None)


def _new_job(query: str) -> str:
    job_id = uuid.uuid4().hex

    with JOBS_LOCK:
        JOBS[job_id] = {
            "job_id": job_id,
            "query": query,
            "started_at": time.time(),
            "completed": False,
            "partial": False,
            "results": [],
            "comparisons": [],
            "errors": {},
            "stores": {},
            "elapsed": 0.0,
        }

    _cleanup_jobs()
    return job_id


def _snapshot(job_id: str) -> Dict[str, Any]:
    with JOBS_LOCK:
        job = JOBS.get(job_id)

        if not job:
            return {
                "job_id": job_id,
                "query": "",
                "completed": True,
                "partial": False,
                "results": [],
                "comparisons": [],
                "errors": {
                    "job": "job_not_found"
                },
                "stores": {},
                "elapsed": 0.0,
            }

        return copy.deepcopy(job)


def _run_job(
    job_id: str,
    query: str,
) -> None:
    started = time.monotonic()

    for store in STORES:
        report = run_store(
            store,
            query,
            use_cache=True,
        )

        with JOBS_LOCK:
            job = JOBS.get(job_id)

            if not job:
                return

            job["stores"][store] = {
                "status": report["status"],
                "cache": report.get("cache"),
                "count": report["count"],
                "elapsed": report["elapsed"],
            }

            if report.get("error"):
                job["errors"][store] = report["error"]

            job["results"].extend(
                report.get("results", [])
            )

            job["results"] = sort_results(
                dedupe_results(job["results"])
            )

            job["comparisons"] = (
                build_comparisons(
                    job["results"]
                )
            )

            job["elapsed"] = round(
                time.monotonic() - started,
                3,
            )

        gc.collect()

    with JOBS_LOCK:
        job = JOBS.get(job_id)

        if job:
            job["results"] = sort_results(
                dedupe_results(
                    job["results"]
                )
            )
            job["comparisons"] = (
                build_comparisons(
                    job["results"]
                )
            )
            job["completed"] = True
            job["partial"] = False
            job["elapsed"] = round(
                time.monotonic() - started,
                3,
            )


# ============================================================================
# API
# ============================================================================

@app.get("/")
def root():
    if FRONTEND_INDEX.exists():
        return FileResponse(
            FRONTEND_INDEX,
            media_type="text/html",
        )

    return {
        "app": "ScentHunter",
        "status": "running",
        "architecture": "sequential-live-scrapers",
        "stores": STORES,
        "error": "frontend/index.html not found",
    }


@app.get("/health")
def health():
    try:
        load_matcher()
        matcher_loaded = True
    except Exception as exc:
        logger.exception(
            "MATCHER INIT FAILED: %s",
            exc,
        )
        matcher_loaded = False

    return {
        "status": (
            "healthy"
            if matcher_loaded
            else "degraded"
        ),
        "architecture": "sequential-live-scrapers-matcher",
        "stores": STORES,
        "matcher_loaded": matcher_loaded,
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
    }


@app.get("/search")
def search_perfume(
    q: str,
    fresh: bool = False,
):
    query = str(q or "").strip()

    if not query:
        return {
            "query": "",
            "count": 0,
            "results": [],
            "comparisons": [],
            "errors": {},
            "stores": {},
            "partial": False,
            "elapsed": 0.0,
        }

    logger.info(
        "SEARCH START | query=%r | fresh=%s",
        query,
        fresh,
    )

    data = run_search(
        query=query,
        use_cache=not fresh,
    )

    logger.info(
        "SEARCH END | query=%r | results=%s | elapsed=%ss",
        query,
        data["count"],
        data["elapsed"],
    )

    return data


@app.get("/search-start")
def search_start(q: str):
    query = str(q or "").strip()

    if not query:
        return {
            "job_id": "",
            "query": "",
            "completed": True,
            "partial": False,
            "results": [],
            "comparisons": [],
            "errors": {},
            "stores": {},
            "elapsed": 0.0,
        }

    job_id = _new_job(query)

    thread = threading.Thread(
        target=_run_job,
        args=(job_id, query),
        daemon=True,
        name=f"scenthunter-job-{job_id[:8]}",
    )
    thread.start()

    return _snapshot(job_id)


@app.get("/search-status/{job_id}")
def search_status_path(job_id: str):
    return _snapshot(job_id)


@app.get("/search-status")
def search_status_query(job_id: str):
    return _snapshot(job_id)


# ============================================================================
# DIAGNOSTICA
# ============================================================================

@app.get("/test-store")
def test_store(
    store: str,
    q: str,
    fresh: bool = True,
):
    store = str(store or "").strip().lower()
    query = str(q or "").strip()

    if store not in STORES:
        return {
            "ok": False,
            "store": store,
            "query": query,
            "error": "unknown_store",
            "stores": STORES,
        }

    report = run_store(
        store,
        query,
        use_cache=not fresh,
    )

    return {
        "ok": report["status"] not in {
            "error",
            "timeout",
        },
        "query": query,
        **report,
    }


@app.get("/diagnose-stores")
def diagnose_stores(
    q: str = "Liquid Brun",
):
    data = run_search(
        query=str(q or "").strip(),
        use_cache=False,
    )

    return {
        "ok": True,
        "architecture": "sequential-live-scrapers",
        **data,
    }


@app.get("/cache/clear")
def clear_cache():
    _cache_clear()

    return {
        "ok": True,
        "cache": "cleared",
    }


@app.get("/frontend")
def frontend():
    if FRONTEND_INDEX.exists():
        return FileResponse(
            FRONTEND_INDEX,
            media_type="text/html",
        )

    return {
        "error": "frontend/index.html not found"
    }


# ============================================================================
# LOCAL
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
    )
