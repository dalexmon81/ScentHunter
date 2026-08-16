from fastapi import FastAPI, HTTPException
import importlib
import inspect
import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

app = FastAPI(title="ScentHunter - Deloox REAL Diagnostic", version="2.0")

# IMPORTANTE: questo Main NON cerca un file inventato.
# Carica ESATTAMENTE lo scraper usato dal progetto:
# /app/backend/scrapers/deloox/scraper.py
MODULE_NAME = "scrapers.deloox.scraper"


def load_scraper():
    return importlib.import_module(MODULE_NAME)


def run_timeout(label, fn, timeout=15):
    started = time.perf_counter()
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    try:
        value = future.result(timeout=timeout)
        return {
            "step": label,
            "status": "OK",
            "seconds": round(time.perf_counter() - started, 3),
            "value": value,
        }
    except FutureTimeout:
        future.cancel()
        return {
            "step": label,
            "status": "TIMEOUT",
            "seconds": round(time.perf_counter() - started, 3),
            "timeout": timeout,
            "message": "La funzione non ha restituito entro il limite diagnostico.",
        }
    except Exception as exc:
        return {
            "step": label,
            "status": "ERROR",
            "seconds": round(time.perf_counter() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def safe_repr(value, limit=12000):
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = repr(value)
    return text[:limit]


@app.get("/")
def root():
    return {
        "status": "ok",
        "diagnostic": "REAL",
        "scraper_module": MODULE_NAME,
        "tests": [
            "/diagnose-deloox?q=Hawas%20Kobra",
            "/diagnose-deloox?q=Liquid%20Brun",
            "/diagnose-deloox?q=Hawas%20for%20Him",
        ],
    }


@app.get("/diagnose-deloox")
def diagnose_deloox(q: str):
    query = (q or "").strip()
    if not query:
        raise HTTPException(400, "Parametro q mancante")

    report = {"query": query, "scraper_module": MODULE_NAME, "steps": []}

    # 1. Carica lo scraper REALE del progetto.
    try:
        scraper = load_scraper()
        report["steps"].append({
            "step": "1_load_real_scraper",
            "status": "OK",
            "module_file": getattr(scraper, "__file__", None),
        })
    except Exception as exc:
        report["steps"].append({
            "step": "1_load_real_scraper",
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })
        return report

    # 2. Mostra le funzioni reali e le loro firme.
    names = [
        "_candidate_queries", "_candidate_product_urls", "_discover",
        "_discover_from_categories", "_sitemap_product_urls", "search"
    ]
    functions = {}
    for name in names:
        obj = getattr(scraper, name, None)
        functions[name] = {
            "exists": obj is not None,
            "signature": str(inspect.signature(obj)) if callable(obj) else None,
        }
    report["steps"].append({"step": "2_real_structure", "status": "OK", "functions": functions})

    # 3. Le query che lo scraper costruisce davvero.
    candidate_fn = getattr(scraper, "_candidate_queries", None)
    if callable(candidate_fn):
        report["steps"].append(run_timeout(
            "3_candidate_queries",
            lambda: candidate_fn(query),
            timeout=5,
        ))
    else:
        report["steps"].append({"step": "3_candidate_queries", "status": "MISSING"})

    # 4. Testiamo direttamente search() dello scraper REALE.
    # Niente filtro Main, niente categorie aggiunte dal Main, niente Deloox finto.
    search_fn = getattr(scraper, "search", None)
    if not callable(search_fn):
        report["steps"].append({"step": "4_real_search", "status": "MISSING"})
        return report

    result = run_timeout(
        "4_real_search",
        lambda: search_fn(query),
        timeout=20,
    )
    if "value" in result:
        value = result.pop("value")
        result["result_type"] = type(value).__name__
        result["result_count"] = len(value) if hasattr(value, "__len__") else None
        result["result_preview"] = safe_repr(value)
    report["steps"].append(result)

    # 5. Se search() ha restituito prodotti, evidenziamo solo Deloox.
    if "value" in result:
        pass

    # 6. Se esiste _discover(), lo testiamo separatamente.
    discover_fn = getattr(scraper, "_discover", None)
    if callable(discover_fn):
        try:
            sig = inspect.signature(discover_fn)
            params = list(sig.parameters)
            if len(params) == 2:
                # Caso tipico: _discover(session, query)
                session_cls = getattr(scraper, "requests", None)
                session = session_cls.Session() if session_cls else None
                if session is not None:
                    report["steps"].append(run_timeout(
                        "5_real_discover",
                        lambda: discover_fn(session, query),
                        timeout=20,
                    ))
            else:
                report["steps"].append({
                    "step": "5_real_discover",
                    "status": "SKIPPED",
                    "reason": f"firma non compatibile: {sig}",
                })
        except Exception as exc:
            report["steps"].append({
                "step": "5_real_discover",
                "status": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            })

    report["diagnosis"] = (
        "Questo test usa direttamente scrapers.deloox.scraper del progetto. "
        "Se 4_real_search restituisce 0 prodotti, il problema è nello scraper Deloox; "
        "se restituisce prodotti ma il Main non li mostra, il problema è nel Main/normalizzazione."
    )
    return report
