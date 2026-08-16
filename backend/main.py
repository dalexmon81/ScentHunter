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


@app.get("/diagnose-deloox-direct")
def diagnose_deloox_direct(q: str = "Liquid Brun"):
    """Diagnostica minima: pagina categoria reale -> candidati prodotto.

    Non esegue search(), _discover() o sitemap traversal. Serve a isolare
    il punto esatto in cui Deloox smette di produrre URL prodotto.
    """
    query = (q or "").strip()
    if not query:
        raise HTTPException(400, "Parametro q mancante")

    report = {
        "query": query,
        "scraper_module": MODULE_NAME,
        "steps": [],
    }

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

    category_url = (
        "https://www.deloox.com/en/category/1132834/liquid-brun.html"
        if "liquid brun" in query.lower()
        else None
    )
    if not category_url:
        report["steps"].append({
            "step": "2_category_seed",
            "status": "SKIPPED",
            "message": "Il test diretto attuale è predisposto per Liquid Brun.",
        })
        return report

    session = scraper.requests.Session()
    try:
        r = session.get(
            category_url,
            headers=getattr(scraper, "HEADERS", {}),
            timeout=15,
        )
        html = r.text or ""
        report["steps"].append({
            "step": "2_fetch_liquid_brun_category",
            "status": "OK" if r.status_code < 400 else "HTTP_ERROR",
            "http_status": r.status_code,
            "bytes": len(r.content),
            "elapsed_hint": None,
            "url": category_url,
            "product_path_occurrences": html.lower().count("/product/"),
            "category_path_occurrences": html.lower().count("/category/"),
            "sku_1385920_occurrences": html.count("1385920"),
        })
    except Exception as exc:
        report["steps"].append({
            "step": "2_fetch_liquid_brun_category",
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })
        return report

    candidate_fn = getattr(scraper, "_candidate_product_urls", None)
    if not callable(candidate_fn):
        report["steps"].append({
            "step": "3_candidate_product_urls",
            "status": "MISSING",
        })
        return report

    try:
        candidates = candidate_fn(
            html,
            query,
            accept_all_products=True,
        )
        report["steps"].append({
            "step": "3_candidate_product_urls",
            "status": "OK",
            "count": len(candidates),
            "candidates": candidates[:30],
            "contains_1385920": any("1385920" in u for u in candidates),
        })
    except Exception as exc:
        report["steps"].append({
            "step": "3_candidate_product_urls",
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })
        return report

    category_line_fn = getattr(scraper, "_category_product_line_links", None)
    if callable(category_line_fn):
        try:
            links = category_line_fn(html, query)
            report["steps"].append({
                "step": "4_product_line_links",
                "status": "OK",
                "count": len(links),
                "links": links[:20],
            })
        except Exception as exc:
            report["steps"].append({
                "step": "4_product_line_links",
                "status": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
            })

    report["diagnosis"] = (
        "Questo endpoint isola esclusivamente categoria -> URL prodotto. "
        "Se qui compare 1385920, Deloox espone il prodotto e il problema "
        "non è la scoperta della categoria. Se product_path_occurrences > 0 "
        "ma candidate count = 0, il punto da correggere è _candidate_product_urls. "
        "Se entrambi sono 0, il problema è la risposta della categoria."
    )
    return report


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
