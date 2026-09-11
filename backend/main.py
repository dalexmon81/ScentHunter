"""
ScentHunter - LIVE SEARCH ORCHESTRATOR

Architettura:
- 8 scraper indipendenti
- nessun SearchEngine / main_legacy / product_index
- tutti gli store partono in parallelo
- un errore/timeout di uno store NON blocca gli altri
- cache breve per rendere le ricerche ripetute immediate
- fallback alla cache stale se uno store è temporaneamente bloccato
- risultati normalizzati solo a livello di trasporto
- confronto finale costruito da offerte reali, senza prezzi hard-coded

Gli scraper esistenti restano autonomi. Il contratto minimo atteso è:
    search(query) -> iterable[dict]

Campi normalmente supportati:
    brand, name/title, price/price_num, size_ml, url,
    available/in_stock, store/shop, image...
"""

from __future__ import annotations

import copy
import gc
import importlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse


# ============================================================================
# APP
# ============================================================================

app = FastAPI(
    title="ScentHunter API",
    version="4.2-progressive-isolated-render-safe",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# CONFIGURAZIONE
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

# Render Free: teniamo bassa la concorrenza per evitare contention RAM/CPU.
SEARCH_MAX_WORKERS = 2

# Timeout individuale per singolo store (worker isolato).
# 15s è più realistico su Render Free rispetto a 12s.
STORE_TIMEOUT_SECONDS = 15.0

# Timeout hard orchestrazione job complessiva.
JOB_HARD_TIMEOUT_SECONDS = 60.0

# Cache fresh: una seconda ricerca identica viene servita quasi subito.
CACHE_TTL_SECONDS = 90.0

# Cache stale: se un negozio è momentaneamente KO, possiamo mostrare l'ultimo
# risultato reale disponibile invece di trasformare un errore transitorio in
# "nessun prodotto".
CACHE_STALE_SECONDS = 15 * 60.0

# Massimo numero di offerte mantenute per store/query. Evita esplosioni di
# memoria dovute a ricerche troppo generiche.
MAX_RESULTS_PER_STORE = 80

# Numero massimo di elementi in una singola comparazione.
MAX_OFFERS_PER_COMPARISON = 100

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | ScentHunter | %(message)s",
)
logger = logging.getLogger("scent-hunter")


# ============================================================================
# CACHE
# ============================================================================

_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()


def _cache_key(store: str, query: str) -> Tuple[str, str]:
    return (
        str(store).strip().lower(),
        _norm_text(query),
    )


def _cache_get(
    store: str,
    query: str,
    allow_stale: bool = True,
) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    key = _cache_key(store, query)

    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if not entry:
            return None, "miss"

        age = time.monotonic() - float(entry.get("saved_at", 0.0))

        if age <= CACHE_TTL_SECONDS:
            return copy.deepcopy(entry.get("results", [])), "fresh"

        if allow_stale and age <= CACHE_STALE_SECONDS:
            return copy.deepcopy(entry.get("results", [])), "stale"

        _CACHE.pop(key, None)
        return None, "expired"


def _cache_put(store: str, query: str, results: List[Dict[str, Any]]) -> None:
    key = _cache_key(store, query)

    with _CACHE_LOCK:
        _CACHE[key] = {
            "saved_at": time.monotonic(),
            "results": copy.deepcopy(results),
        }


def _cache_clear() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


# ============================================================================
# HELPERS
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

    text = str(value).strip()
    if not text:
        return None

    text = text.replace("\xa0", " ")
    text = text.replace(",", ".")

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
    if not text:
        return None

    ml_match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*ml\b", text)
    if ml_match:
        return float(ml_match.group(1))

    cl_match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*cl\b", text)
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
            return [raw]

    if isinstance(raw, list):
        iterable: Iterable[Any] = raw
    elif isinstance(raw, tuple):
        iterable = raw
    else:
        try:
            iterable = list(raw)
        except TypeError:
            return []

    rows: List[Dict[str, Any]] = []
    for item in iterable:
        if isinstance(item, dict):
            rows.append(dict(item))

    return rows


def clean_result(item: Dict[str, Any], store: str) -> Dict[str, Any]:
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
        for key in ("title", "product_name", "productTitle"):
            if result.get(key):
                result["name"] = str(result[key]).strip()
                break

    if result.get("brand") is not None:
        result["brand"] = str(result["brand"]).strip()

    if result.get("name") is not None:
        result["name"] = str(result["name"]).strip()

    if result.get("size_ml") in (None, ""):
        for key in ("volume_ml", "format_ml", "size_ml", "size", "volume", "format"):
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
        for key in ("price", "current_price", "sale_price"):
            parsed = _safe_float(result.get(key))
            if parsed is not None:
                result["price_num"] = parsed
                break
    else:
        result["price_num"] = _safe_float(result.get("price_num"))

    if "available" in result:
        if result["available"] is None:
            result["available"] = None
        elif isinstance(result["available"], str):
            low = _norm_text(result["available"])
            if low in {"true", "1", "yes", "available", "in stock"}:
                result["available"] = True
            elif low in {"false", "0", "no", "unavailable", "out of stock"}:
                result["available"] = False
            else:
                result["available"] = None
        else:
            result["available"] = bool(result["available"])
    elif "in_stock" in result:
        value = result.get("in_stock")
        if value is None:
            result["available"] = None
        elif isinstance(value, str):
            low = _norm_text(value)
            if low in {"true", "1", "yes", "available", "in stock"}:
                result["available"] = True
            elif low in {"false", "0", "no", "unavailable", "out of stock"}:
                result["available"] = False
            else:
                result["available"] = None
        else:
            result["available"] = bool(value)
    else:
        result["available"] = None

    if not result.get("url"):
        for key in ("product_url", "link", "href"):
            if result.get(key):
                result["url"] = str(result[key]).strip()
                break

    return result


def result_key(item: Dict[str, Any]) -> Tuple[str, str, str, str]:
    store = _normalise_store(item.get("store") or item.get("shop"), "")

    product_id = str(
        item.get("store_product_id")
        or item.get("product_id")
        or item.get("sku")
        or item.get("mpn")
        or ""
    ).strip().lower()

    url = str(item.get("url") or item.get("product_url") or "").strip().lower()
    name = _norm_text(item.get("name") or item.get("title") or "")
    brand = _norm_text(item.get("brand") or "")

    size = item.get("size_ml")
    try:
        size_key = f"{float(size):.3f}" if size is not None else ""
    except (TypeError, ValueError):
        size_key = ""

    stable = url or product_id or f"{brand}|{name}"

    return (
        store,
        stable,
        size_key,
        _norm_text(item.get("variant") or item.get("concentration") or ""),
    )


def dedupe_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    output: List[Dict[str, Any]] = []
    for item in results:
        key = result_key(item)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _stock_rank(item: Dict[str, Any]) -> int:
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


def sort_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def key(item: Dict[str, Any]):
        rank = _stock_rank(item)
        price = _safe_float(item.get("price_num"))
        size = _safe_float(item.get("size_ml"))
        return (
            rank,
            price if price is not None else float("inf"),
            size if size is not None else float("inf"),
            _norm_text(item.get("shop")),
            _norm_text(item.get("name")),
        )

    return sorted(results, key=key)


# ============================================================================
# CONFRONTO
# ============================================================================

def _comparison_identity(item: Dict[str, Any]) -> Tuple[str, str, str]:
    brand = str(item.get("canonical_brand") or item.get("brand") or "").strip()
    name = str(item.get("canonical_name") or item.get("name") or item.get("title") or "").strip()
    concentration = str(item.get("concentration") or item.get("type") or "").strip()

    return (_norm_text(brand), _norm_text(name), _norm_text(concentration))


def build_comparisons(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}

    for item in results:
        brand, name, concentration = _comparison_identity(item)
        if not name:
            continue
        groups.setdefault((brand, name, concentration), []).append(item)

    comparisons: List[Dict[str, Any]] = []

    for _, offers in groups.items():
        offers = dedupe_results(offers)
        offers = sort_results(offers)
        if not offers:
            continue

        first = offers[0]
        brand = str(first.get("canonical_brand") or first.get("brand") or "").strip()
        name = str(first.get("canonical_name") or first.get("name") or first.get("title") or "").strip()
        concentration = str(first.get("concentration") or "").strip()

        formats = sorted({
            round(float(item["size_ml"]), 3)
            for item in offers
            if item.get("size_ml") is not None and _safe_float(item.get("size_ml")) is not None
        })

        comparisons.append({
            "brand": brand,
            "name": name,
            "canonical_brand": str(first.get("canonical_brand") or brand).strip(),
            "canonical_name": str(first.get("canonical_name") or name).strip(),
            "concentration": concentration,
            "formats": formats,
            "offers": offers[:MAX_OFFERS_PER_COMPARISON],
            "count": len(offers),
        })

    def comparison_key(group: Dict[str, Any]):
        offers = group.get("offers", [])
        best_price = float("inf")
        for offer in offers:
            if offer.get("available") is False:
                continue
            price = _safe_float(offer.get("price_num"))
            if price is not None:
                best_price = min(best_price, price)
        return (
            best_price,
            _norm_text(group.get("brand")),
            _norm_text(group.get("name")),
        )

    comparisons.sort(key=comparison_key)
    return comparisons


# ============================================================================
# SCRAPER LOADING
# ============================================================================

def load_scraper(store: str):
    return importlib.import_module(f"scrapers.{store}.scraper")


# ============================================================================
# STORE RUNNER
# ============================================================================

def _scraper_worker(store: str, query: str) -> int:
    try:
        module = load_scraper(store)
        search = getattr(module, "search", None)
        if not callable(search):
            raise RuntimeError(f"scraper {store} non espone search(query)")

        raw = search(query)
        rows = _coerce_rows(raw)
        sys.stdout.write(json.dumps({"ok": True, "rows": rows}, ensure_ascii=False, default=str) + "\n")
        sys.stdout.flush()
        return 0
    except BaseException as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        return 1


def _terminate_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return

    # 1) Graceful terminate
    try:
        process.terminate()
    except Exception:
        pass

    # 2) Wait breve
    try:
        process.wait(timeout=1.0)
        return
    except Exception:
        pass

    # 3) Hard kill gruppo processo (Linux/Render)
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except Exception:
        try:
            process.kill()
        except Exception:
            pass

    # 4) Last wait
    try:
        process.wait(timeout=1.5)
    except Exception:
        pass


def _run_scraper_isolated(store: str, query: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--scenthunter-worker",
        store,
        query,
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BASE_DIR) + os.pathsep + env.get("PYTHONPATH", "")

    process = None
    try:
        process = subprocess.Popen(
            command,
            cwd=str(BASE_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=(os.name != "nt"),
        )

        stdout, stderr = process.communicate(timeout=STORE_TIMEOUT_SECONDS)

        payload = None
        for line in reversed((stdout or "").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and ("ok" in candidate or "rows" in candidate):
                payload = candidate
                break

        if process.returncode != 0:
            error = f"worker_exit_{process.returncode}"
            if isinstance(payload, dict) and payload.get("error"):
                error += ": " + str(payload["error"])
            elif stderr and stderr.strip():
                error += ": " + stderr.strip()[-800:]
            return [], error

        if not isinstance(payload, dict) or payload.get("ok") is not True:
            return [], "worker_invalid_response"

        return _coerce_rows(payload.get("rows")), None

    except subprocess.TimeoutExpired:
        if process is not None:
            _terminate_process_tree(process)
        return [], f"timeout_after_{STORE_TIMEOUT_SECONDS:g}s"

    except Exception as exc:
        if process is not None:
            _terminate_process_tree(process)
        return [], f"{type(exc).__name__}: {exc}"


def run_store(store: str, query: str, use_cache: bool = True) -> Dict[str, Any]:
    started = time.monotonic()
    query = str(query or "").strip()

    if use_cache:
        cached, cache_state = _cache_get(store, query, allow_stale=True)
        if cached is not None and cache_state == "fresh":
            return {
                "store": store,
                "status": "cache",
                "cache": "fresh",
                "elapsed": round(time.monotonic() - started, 3),
                "count": len(cached),
                "results": cached,
                "error": None,
            }

    try:
        raw_rows, worker_error = _run_scraper_isolated(store, query)
        if worker_error:
            raise RuntimeError(worker_error)

        cleaned = [clean_result(row, store) for row in raw_rows[:MAX_RESULTS_PER_STORE]]
        cleaned = dedupe_results(cleaned)
        cleaned = sort_results(cleaned)

        matched = cleaned

        if matched:
            _cache_put(store, query, matched)

        elapsed = round(time.monotonic() - started, 3)
        logger.info("STORE END | %s | results=%s | elapsed=%ss", store, len(matched), elapsed)

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
        error_text = f"{type(exc).__name__}: {exc}"
        logger.warning("STORE ERROR | %s | query=%r | %s", store, query, error_text)

        stale, stale_state = _cache_get(store, query, allow_stale=True)
        if stale is not None and stale_state == "stale":
            return {
                "store": store,
                "status": "stale",
                "cache": "stale",
                "elapsed": round(time.monotonic() - started, 3),
                "count": len(stale),
                "results": stale,
                "error": error_text,
            }

        return {
            "store": store,
            "status": "error",
            "cache": "miss",
            "elapsed": round(time.monotonic() - started, 3),
            "count": 0,
            "results": [],
            "error": error_text,
        }

    finally:
        gc.collect()


# ============================================================================
# SEARCH ORCHESTRATOR
# ============================================================================

def run_search(query: str, use_cache: bool = True) -> Dict[str, Any]:
    query = str(query or "").strip()
    started = time.monotonic()

    reports: List[Dict[str, Any]] = []
    all_results: List[Dict[str, Any]] = []

    for store in STORES:
        report = run_store(store, query, use_cache=use_cache)
        reports.append(report)
        all_results.extend(report.get("results", []))
        gc.collect()

    all_results = sort_results(dedupe_results(all_results))
    comparisons = build_comparisons(all_results)
    errors = {report["store"]: report["error"] for report in reports if report.get("error")}

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
        "elapsed": round(time.monotonic() - started, 3),
    }


# ============================================================================
# JOBS - COMPATIBILITÀ CON IL FRONTEND CHE USA /search-start
# ============================================================================

JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
MAX_JOBS = 40


def _cleanup_jobs() -> None:
    with JOBS_LOCK:
        if len(JOBS) <= MAX_JOBS:
            return
        ordered = sorted(JOBS.items(), key=lambda pair: pair[1].get("started_at", 0.0))
        remove_count = len(JOBS) - MAX_JOBS
        for job_id, _ in ordered[:remove_count]:
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
                "errors": {"job": "job_not_found"},
                "stores": {},
                "elapsed": 0.0,
            }
        return copy.deepcopy(job)


def _publish_store_report(job_id: str, report: Dict[str, Any], started: float) -> None:
    store = str(report.get("store") or "").strip().lower()
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None or job.get("completed"):
            return

        job["stores"][store] = {
            "status": report["status"],
            "cache": report.get("cache"),
            "count": report["count"],
            "elapsed": report["elapsed"],
        }

        if report.get("error"):
            job["errors"][store] = report["error"]

        job["results"].extend(report.get("results", []))
        job["results"] = sort_results(dedupe_results(job["results"]))
        job["comparisons"] = build_comparisons(job["results"])
        job["partial"] = len(job["stores"]) < len(STORES)
        job["elapsed"] = round(time.monotonic() - started, 3)


def _run_job(job_id: str, query: str) -> None:
    started = time.monotonic()

    try:
        from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

        max_workers = max(1, int(SEARCH_MAX_WORKERS))
        pending_stores = list(STORES)
        in_flight = {}

        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="scent_store") as executor:
            # Avvio immediato primi slot
            while pending_stores and len(in_flight) < max_workers:
                store = pending_stores.pop(0)
                future = executor.submit(run_store, store, query, True)
                in_flight[future] = store

            while in_flight:
                with JOBS_LOCK:
                    job = JOBS.get(job_id)
                    if job is None or job.get("completed"):
                        return

                if time.monotonic() - started >= JOB_HARD_TIMEOUT_SECONDS:
                    with JOBS_LOCK:
                        job = JOBS.get(job_id)
                        if job and not job.get("completed"):
                            job["errors"]["job"] = (
                                "Ricerca completata con i risultati disponibili: "
                                "tempo massimo orchestrazione raggiunto."
                            )
                            job["partial"] = len(job.get("stores", {})) < len(STORES)
                    break

                done, _ = wait(
                    set(in_flight.keys()),
                    timeout=0.5,
                    return_when=FIRST_COMPLETED,
                )
                if not done:
                    continue

                for fut in done:
                    store = in_flight.pop(fut, None)
                    if not store:
                        continue

                    try:
                        report = fut.result()
                    except Exception as exc:
                        report = {
                            "store": store,
                            "status": "error",
                            "cache": "miss",
                            "elapsed": round(time.monotonic() - started, 3),
                            "count": 0,
                            "results": [],
                            "error": f"{type(exc).__name__}: {exc}",
                        }

                    _publish_store_report(job_id, report, started)
                    gc.collect()

                    # Slot libero -> parte subito prossimo store
                    if pending_stores:
                        next_store = pending_stores.pop(0)
                        next_fut = executor.submit(run_store, next_store, query, True)
                        in_flight[next_fut] = next_store

    except Exception as exc:
        logger.exception("SEARCH JOB ERROR | job=%s | query=%r | %s", job_id, query, exc)
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job:
                job["errors"]["job"] = f"{type(exc).__name__}: {exc}"

    finally:
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job:
                job["results"] = sort_results(dedupe_results(job["results"]))
                job["comparisons"] = build_comparisons(job["results"])
                job["completed"] = True
                job["partial"] = len(job.get("stores", {})) < len(STORES)
                job["elapsed"] = round(time.monotonic() - started, 3)


@app.get("/search")
def search_perfume(q: str, fresh: bool = False):
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

    logger.info("SEARCH START | query=%r | fresh=%s", query, fresh)

    data = run_search(query=query, use_cache=not fresh)

    logger.info(
        "SEARCH END | query=%r | results=%s | elapsed=%ss | stores=%s/%s",
        query,
        data["count"],
        data["elapsed"],
        data["completed_stores"],
        data["total_stores"],
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
        name=f"scenthunter-search-job-{job_id[:8]}",
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
def test_store(store: str, q: str, fresh: bool = True):
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

    report = run_store(store, query, use_cache=not fresh)

    return {
        "ok": report["status"] not in {"error", "timeout"},
        "query": query,
        **report,
    }


@app.get("/diagnose-stores")
def diagnose_stores(q: str = "Liquid Brun"):
    data = run_search(query=str(q or "").strip(), use_cache=False)

    return {
        "ok": True,
        "architecture": "sequential-isolated-scrapers",
        **data,
    }


@app.get("/cache/clear")
def clear_cache():
    _cache_clear()
    return {"ok": True, "cache": "cleared"}


# ============================================================================
# FRONTEND
# ============================================================================

@app.get("/", include_in_schema=False)
def root_frontend():
    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX)
    return {"error": "frontend/index.html not found"}


@app.get("/frontend")
def frontend():
    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX)
    return {"error": "frontend/index.html not found"}


@app.get("/diagnose-frontend")
def diagnose_frontend():
    import hashlib

    data = {
        "diagnostic": True,
        "frontend_path": str(FRONTEND_INDEX),
        "exists": FRONTEND_INDEX.exists(),
    }
    if not FRONTEND_INDEX.exists():
        return data

    raw = FRONTEND_INDEX.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    data.update({
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "has_search_endpoint": "/search?q=" in text or 'backend()+"/search' in text,
        "has_search_start": "/search-start" in text,
        "has_search_status": "/search-status" in text,
        "has_openProduct": "function openProduct(" in text,
        "has_openSize": "function openSize(" in text,
        "has_detail_not_found": "detail not found" in text.lower(),
        "has_detail_view": "detail-approved" in text,
        "has_shGroupData": "function shGroupData(" in text,
        "has_comparisons": "data.comparisons" in text,
        "search_calls": text.count('"/search?q="'),
        "search_start_calls": text.count('/search-start'),
    })
    return data


# ============================================================================
# LOCAL ENTRYPOINT
# ============================================================================

if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--scenthunter-worker":
        worker_store = str(sys.argv[2] or "").strip().lower()
        worker_query = str(sys.argv[3] or "").strip()
        if worker_store not in STORES:
            sys.stdout.write(json.dumps({"ok": False, "error": "unknown_store"}) + "\n")
            raise SystemExit(1)
        raise SystemExit(_scraper_worker(worker_store, worker_query))

    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
