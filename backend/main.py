from fastapi import FastAPI, HTTPException
import importlib
import inspect
import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

app = FastAPI(title="ScentHunter - Deloox REAL Diagnostic", version="2.1")

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
            "/diagnose-deloox?q=Hawas%20for%20Him",
            "/diagnose-deloox?q=Liquid%20Brun",
        ],
    }


@app.get("/diagnose-deloox")
def diagnose_deloox(q: str):
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

    names = [
        "_candidate_queries",
        "_candidate_product_urls",
        "_discover",
        "_discover_from_categories",
        "_sitemap_product_urls",
        "_search",
        "_product",
        "search",
    ]

    functions = {}
    for name in names:
        obj = getattr(scraper, name, None)
        functions[name] = {
            "exists": obj is not None,
            "signature": str(inspect.signature(obj))
            if callable(obj)
            else None,
        }

    report["steps"].append({
        "step": "2_real_structure",
        "status": "OK",
        "functions": functions,
    })

    candidate_fn = getattr(scraper, "_candidate_queries", None)
    if callable(candidate_fn):
        report["steps"].append(run_timeout(
            "3_candidate_queries",
            lambda: candidate_fn(query),
            timeout=5,
        ))

    search_fn = getattr(scraper, "search", None)
    if not callable(search_fn):
        report["steps"].append({
            "step": "4_real_search",
            "status": "MISSING",
        })
        return report

    result = run_timeout(
        "4_real_search",
        lambda: search_fn(query),
        timeout=35,
    )

    if "value" in result:
        value = result.pop("value")
        result["result_type"] = type(value).__name__
        result["result_count"] = (
            len(value) if hasattr(value, "__len__") else None
        )
        result["result_preview"] = safe_repr(value)

    report["steps"].append(result)

    # Decisive diagnostic:
    # run discovery, then fetch each discovered URL and call _product()
    # directly. This tells us exactly whether products are lost during
    # page fetching/validation after discovery.
    discover_fn = getattr(scraper, "_discover", None)
    product_fn = getattr(scraper, "_product", None)
    requests_mod = getattr(scraper, "requests", None)

    if callable(discover_fn) and callable(product_fn) and requests_mod:
        def fallback_validation():
            session = requests_mod.Session()

            urls = discover_fn(session, query)
            checks = []

            for url in list(urls)[:12]:
                entry = {
                    "url": url,
                }

                try:
                    page = session.get(
                        url,
                        headers=getattr(scraper, "HEADERS", {}),
                        timeout=getattr(scraper, "TIMEOUT", 4),
                    )

                    entry["http_status"] = page.status_code

                    if page.status_code >= 400:
                        entry["product_result"] = "HTTP_ERROR"
                        checks.append(entry)
                        continue

                    item = product_fn(
                        url,
                        page.text,
                        query,
                    )

                    if item:
                        entry["product_result"] = "ACCEPTED"
                        entry["name"] = item.get("name")
                        entry["price"] = item.get("price")
                        entry["url"] = item.get("url")
                    else:
                        entry["product_result"] = "REJECTED"
                        entry["reason"] = (
                            "_product() returned None"
                        )

                except Exception as exc:
                    entry["product_result"] = "ERROR"
                    entry["error"] = (
                        f"{type(exc).__name__}: {exc}"
                    )

                checks.append(entry)

            return {
                "discovered_count": len(urls),
                "checked": checks,
                "accepted_count": sum(
                    1 for x in checks
                    if x.get("product_result") == "ACCEPTED"
                ),
                "rejected_count": sum(
                    1 for x in checks
                    if x.get("product_result") == "REJECTED"
                ),
            }

        report["steps"].append(run_timeout(
            "6_discovery_then_product_validation",
            fallback_validation,
            timeout=45,
        ))

    report["diagnosis"] = (
        "4_real_search chiama direttamente search(). "
        "Lo step 6 separa discovery, download pagina e _product(): "
        "se gli URL vengono scoperti ma _product() li rifiuta, "
        "il punto di perdita è la validazione del prodotto."
    )

    return report
