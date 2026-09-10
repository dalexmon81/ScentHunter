"""
ScentHunter - SIMPLE SEARCH ARCHITECTURE

One main.py + independent store scrapers.
No SearchEngine.
No main_legacy.
No ProductMatcher in the live search path.
No validation/finalization pipeline between scraper and frontend.

Every store scraper is called directly. Its returned dictionaries are sent
back to the frontend with only a small, generic cleanup/deduplication step.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import importlib
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List


app = FastAPI(title="ScentHunter API", version="2.0-simple")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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

BASE_DIR = __import__("pathlib").Path(__file__).resolve().parent
FRONTEND_INDEX = BASE_DIR.parent / "frontend" / "index.html"

# Keep the live worker pool deliberately simple. All eight scrapers can run
# independently; one slow/broken store cannot block the others from publishing.
MAX_WORKERS = len(STORES)
STORE_TIMEOUT_SECONDS = 25.0
JOB_TIMEOUT_SECONDS = 55.0


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def load_scraper(store: str):
    return importlib.import_module(f"scrapers.{store}.scraper")


def _safe_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalise_store(value: Any, fallback: str) -> str:
    text = str(value or fallback).strip().lower()
    aliases = {
        "bplatz": "bplatz",
        "bplatz.de": "bplatz",
        "deloox": "deloox",
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
    }
    return aliases.get(text, text)


def clean_result(item: Dict[str, Any], store: str) -> Dict[str, Any]:
    """Only generic transport cleanup. Never decides whether a product matches."""
    result = dict(item)
    machine_store = _normalise_store(result.get("store") or result.get("shop"), store)
    result["store"] = machine_store
    result.setdefault("shop", STORE_LABELS.get(machine_store, machine_store))

    # Preserve the scraper's own values. These fallbacks are only for the
    # common schemas used by the existing independent scrapers.
    if "available" not in result and "in_stock" in result:
        result["available"] = bool(result.get("in_stock"))

    if result.get("size_ml") in (None, ""):
        for key in ("volume_ml", "format_ml", "size"):
            value = result.get(key)
            if value not in (None, ""):
                parsed = _safe_float(value)
                if parsed is not None:
                    result["size_ml"] = parsed
                    break

    if "price_num" not in result:
        parsed = _safe_float(result.get("price"))
        if parsed is not None:
            result["price_num"] = parsed

    return result


def result_key(item: Dict[str, Any]) -> tuple:
    """Conservative duplicate key. Never merges different stores or sizes."""
    store = _normalise_store(item.get("store") or item.get("shop"), "")
    url = str(item.get("url") or item.get("product_url") or "").strip().lower()
    product_id = str(
        item.get("store_product_id")
        or item.get("product_id")
        or item.get("sku")
        or ""
    ).strip().lower()
    name = " ".join(str(item.get("name") or item.get("title") or "").split()).lower()
    size = _safe_float(item.get("size_ml"))
    size_key = round(size, 3) if size is not None else ""

    # URL/product id is strongest. Name+size is only a fallback when the
    # scraper gives no stable product identifier.
    identity = url or product_id or name
    return (store, identity, size_key)


def dedupe_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    output = []
    for item in results:
        key = result_key(item)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def sort_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Available priced offers first, unknown next, out-of-stock last."""
    def key(item):
        available = item.get("available")
        price = _safe_float(item.get("price_num"))
        if available is False:
            stock_rank = 2
        elif price is not None:
            stock_rank = 0
        else:
            stock_rank = 1
        return (stock_rank, price if price is not None else 999999.0)

    return sorted(results, key=key)


# ---------------------------------------------------------------------------
# One store = one independent call
# ---------------------------------------------------------------------------

def run_store(store: str, query: str) -> Dict[str, Any]:
    started = time.monotonic()
    try:
        module = load_scraper(store)
        search = getattr(module, "search")
        raw = search(query)

        # Some future scraper may return a generator/tuple; accept any normal
        # iterable while keeping the contract simple.
        if raw is None:
            rows = []
        elif isinstance(raw, list):
            rows = raw
        elif isinstance(raw, tuple):
            rows = list(raw)
        else:
            try:
                rows = list(raw)
            except TypeError:
                rows = []

        cleaned = [
            clean_result(item, store)
            for item in rows
            if isinstance(item, dict)
        ]

        return {
            "store": store,
            "status": "ok" if cleaned else "empty",
            "elapsed": round(time.monotonic() - started, 3),
            "count": len(cleaned),
            "results": cleaned,
            "error": None,
        }
    except Exception as exc:
        traceback.print_exc()
        return {
            "store": store,
            "status": "error",
            "elapsed": round(time.monotonic() - started, 3),
            "count": 0,
            "results": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# Simple job state for the existing frontend's /search-start polling flow
# ---------------------------------------------------------------------------

JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


def _new_job(query: str) -> str:
    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {
            "job_id": job_id,
            "query": query,
            "started_at": time.time(),
            "completed": False,
            "results": [],
            "comparisons": [],
            "errors": {},
            "stores": {},
        }
    return job_id


def _snapshot(job_id: str) -> Dict[str, Any]:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return {
                "job_id": job_id,
                "query": "",
                "completed": True,
                "results": [],
                "comparisons": [],
                "errors": {"job": "job_not_found"},
            }
        return {
            "job_id": job["job_id"],
            "query": job["query"],
            "completed": job["completed"],
            "results": list(job["results"]),
            "comparisons": list(job["comparisons"]),
            "errors": dict(job["errors"]),
            "stores": dict(job["stores"]),
        }


def _publish_store(job_id: str, report: Dict[str, Any]) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return

        store = report["store"]
        job["stores"][store] = {
            "status": report["status"],
            "elapsed": report["elapsed"],
            "count": report["count"],
        }
        if report.get("error"):
            job["errors"][store] = report["error"]

        job["results"].extend(report["results"])
        job["results"] = dedupe_results(job["results"])
        job["results"] = sort_results(job["results"])


def _run_job(job_id: str, query: str) -> None:
    started = time.monotonic()

    # All independent scrapers start together. No central validation stage,
    # no ProductMatcher, no family registry and no second pass.
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(run_store, store, query): store
            for store in STORES
        }

        for future in as_completed(futures):
            store = futures[future]
            try:
                report = future.result(timeout=STORE_TIMEOUT_SECONDS)
            except Exception as exc:
                report = {
                    "store": store,
                    "status": "error",
                    "elapsed": round(time.monotonic() - started, 3),
                    "count": 0,
                    "results": [],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            _publish_store(job_id, report)

            # If the overall job has exceeded the frontend's comfortable
            # window, finish with whatever independent stores have returned.
            if time.monotonic() - started >= JOB_TIMEOUT_SECONDS:
                break

    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job:
            job["results"] = sort_results(dedupe_results(job["results"]))
            job["completed"] = True
            job["elapsed"] = round(time.monotonic() - started, 3)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {
        "app": "ScentHunter",
        "status": "running",
        "architecture": "simple-main-plus-independent-scrapers",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "architecture": "simple",
        "stores": STORES,
    }


@app.get("/search")
def search_perfume(q: str):
    """Synchronous compatibility endpoint. Calls the eight scrapers directly."""
    query = str(q or "").strip()
    if not query:
        return {"query": "", "count": 0, "results": [], "errors": {}}

    reports = []
    all_results: List[Dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(run_store, store, query): store
            for store in STORES
        }
        for future in as_completed(futures):
            store = futures[future]
            try:
                report = future.result()
            except Exception as exc:
                report = {
                    "store": store,
                    "status": "error",
                    "elapsed": None,
                    "count": 0,
                    "results": [],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            reports.append(report)
            all_results.extend(report["results"])

    results = sort_results(dedupe_results(all_results))
    errors = {
        report["store"]: report["error"]
        for report in reports
        if report.get("error")
    }

    return {
        "query": query,
        "count": len(results),
        "results": results,
        "errors": errors,
        "stores": {
            report["store"]: {
                "status": report["status"],
                "count": report["count"],
                "elapsed": report["elapsed"],
            }
            for report in reports
        },
    }


@app.get("/search-start")
def search_start(q: str):
    query = str(q or "").strip()
    if not query:
        return {
            "job_id": "",
            "query": "",
            "completed": True,
            "results": [],
            "comparisons": [],
            "errors": {},
        }

    job_id = _new_job(query)
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, query),
        daemon=True,
        name=f"scenthunter-search-{job_id[:8]}",
    )
    thread.start()
    return _snapshot(job_id)


@app.get("/search-status/{job_id}")
def search_status_path(job_id: str):
    return _snapshot(job_id)


@app.get("/search-status")
def search_status_query(job_id: str):
    return _snapshot(job_id)


@app.get("/test-store")
def test_store(store: str, q: str):
    store = str(store or "").strip().lower()
    if store not in STORES:
        return {
            "ok": False,
            "store": store,
            "error": "unknown_store",
            "stores": STORES,
        }
    report = run_store(store, str(q or "").strip())
    return {
        "ok": report["status"] != "error",
        "store": store,
        "query": str(q or "").strip(),
        **report,
    }


@app.get("/diagnose-stores")
def diagnose_stores(q: str = "Liquid Brun"):
    """One direct call per scraper; useful after every deploy."""
    query = str(q or "").strip()
    reports = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(run_store, store, query): store
            for store in STORES
        }
        for future in as_completed(futures):
            store = futures[future]
            try:
                reports.append(future.result())
            except Exception as exc:
                reports.append({
                    "store": store,
                    "status": "error",
                    "count": 0,
                    "results": [],
                    "error": f"{type(exc).__name__}: {exc}",
                })

    reports.sort(key=lambda x: STORES.index(x["store"]) if x.get("store") in STORES else 999)
    return {
        "ok": True,
        "architecture": "simple-direct-scrapers",
        "query": query,
        "stores": reports,
        "total_count": sum(x.get("count", 0) for x in reports),
    }


@app.get("/suggest")
def suggest(q: str):
    """Minimal live suggestion endpoint; never blocks the search pipeline."""
    query = str(q or "").strip()
    if len(query) < 2:
        return {"query": query, "count": 0, "suggestions": []}

    suggestions = []
    seen = set()

    # Keep suggestions deliberately small and derived from real scraper hits.
    with ThreadPoolExecutor(max_workers=min(4, MAX_WORKERS)) as executor:
        futures = {
            executor.submit(run_store, store, query): store
            for store in STORES[:4]
        }
        for future in as_completed(futures):
            try:
                report = future.result()
            except Exception:
                continue
            for item in report.get("results", []):
                name = str(item.get("name") or item.get("title") or "").strip()
                brand = str(item.get("brand") or "").strip()
                if not name:
                    continue
                key = f"{brand}|{name}".lower()
                if key in seen:
                    continue
                seen.add(key)
                suggestions.append({
                    "brand": brand,
                    "name": name,
                })
                if len(suggestions) >= 8:
                    break
            if len(suggestions) >= 8:
                break

    return {
        "query": query,
        "count": len(suggestions),
        "suggestions": suggestions[:8],
    }


@app.get("/frontend")
def frontend():
    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX)
    return {"error": "frontend/index.html not found"}
