from fastapi import FastAPI, HTTPException
import importlib.util
import traceback
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from urllib.parse import quote_plus

app = FastAPI(
    title="ScentHunter - Deloox Deep Diagnostic",
    version="1.0",
)

SCRAPER_FILE = Path(__file__).resolve().parent / "scraper_deloox_corretto_da_github.py"


def load_scraper():
    spec = importlib.util.spec_from_file_location(
        "deloox_diagnostic_target",
        SCRAPER_FILE,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Impossibile creare il loader dello scraper Deloox")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def timed_call(label, fn, timeout=8):
    """
    Esegue un singolo stadio in una thread separata.
    Se lo stadio si blocca, l'endpoint diagnostico torna comunque il risultato.
    """
    started = time.perf_counter()
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)

    try:
        value = future.result(timeout=timeout)
        return {
            "step": label,
            "status": "ok",
            "seconds": round(time.perf_counter() - started, 3),
            "value": value,
        }

    except TimeoutError:
        future.cancel()
        return {
            "step": label,
            "status": "TIMEOUT",
            "seconds": round(time.perf_counter() - started, 3),
            "timeout_seconds": timeout,
            "message": (
                "Questo stadio non ha risposto entro il limite. "
                "Il resto della diagnosi continua."
            ),
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


@app.get("/")
def root():
    return {
        "status": "ok",
        "target": SCRAPER_FILE.name,
        "tests": {
            "hawas_kobra": "/diagnose-deloox?q=Hawas%20Kobra",
            "liquid_brun": "/diagnose-deloox?q=Liquid%20Brun",
            "hawas_for_him": "/diagnose-deloox?q=Hawas%20for%20Him",
            "nine_pm": "/diagnose-deloox?q=9PM",
        },
    }


@app.get("/diagnose-deloox")
def diagnose_deloox(q: str):
    query = str(q or "").strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Parametro q mancante",
        )

    report = {
        "query": query,
        "target_scraper": SCRAPER_FILE.name,
        "steps": [],
    }

    # --------------------------------------------------------
    # STEP 1 - carica esattamente lo scraper che stiamo testando
    # --------------------------------------------------------
    try:
        module = load_scraper()
        report["steps"].append({
            "step": "1_load_scraper",
            "status": "OK",
            "module": module.__name__,
        })
    except Exception as exc:
        report["steps"].append({
            "step": "1_load_scraper",
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })
        return report

    # --------------------------------------------------------
    # STEP 2 - funzioni e firme presenti
    # --------------------------------------------------------
    functions = [
        "_candidate_queries",
        "_candidate_product_urls",
        "_discover",
        "_sitemap_product_urls",
        "_discover_from_categories",
        "diagnose_search",
        "search",
    ]

    report["steps"].append({
        "step": "2_structure",
        "status": "OK",
        "functions": {
            name: hasattr(module, name)
            for name in functions
        },
    })

    # --------------------------------------------------------
    # STEP 3 - candidate queries
    # --------------------------------------------------------
    try:
        candidates = module._candidate_queries(query)
        report["steps"].append({
            "step": "3_candidate_queries",
            "status": "OK",
            "queries": candidates,
        })
    except Exception as exc:
        report["steps"].append({
            "step": "3_candidate_queries",
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })
        return report

    # --------------------------------------------------------
    # STEP 4 - DIRECT DELOOX SEARCH ROUTES
    # Questo è il test più importante.
    # Non passa da categorie, sitemap o _discover().
    # --------------------------------------------------------
    direct_routes = [
        "/en/search?query=",
        "/en/search?search=",
        "/en/search?q=",
        "/it/cerca?query=",
    ]

    direct_results = []

    for route in direct_routes:
        url = module.BASE_URL + route + quote_plus(query)

        def request_direct(url=url):
            response = module.requests.get(
                url,
                headers=module.HEADERS,
                timeout=6,
            )

            html = response.text or ""

            candidates = module._candidate_product_urls(
                html,
                query,
                discovery_query=query,
                accept_all_products=True,
            )

            return {
                "url": url,
                "status_code": response.status_code,
                "bytes": len(response.content),
                "content_type": response.headers.get("content-type", ""),
                "candidate_urls": candidates[:30],
                "candidate_count": len(candidates),
                "contains_product_path": "/product/" in html.lower(),
                "contains_query_text": query.lower() in html.lower(),
            }

        direct_results.append(
            timed_call(
                "4_direct_route_" + route,
                request_direct,
                timeout=8,
            )
        )

    report["steps"].extend(direct_results)

    # --------------------------------------------------------
    # STEP 5 - SITEMAP
    # --------------------------------------------------------
    def sitemap_test():
        session = module.requests.Session()
        try:
            urls = module._sitemap_product_urls(
                session,
                query,
                max_sitemaps=2,
                max_urls=20,
            )
            return {
                "count": len(urls),
                "urls": urls[:20],
            }
        finally:
            session.close()

    report["steps"].append(
        timed_call(
            "5_sitemap_product_discovery",
            sitemap_test,
            timeout=12,
        )
    )

    # --------------------------------------------------------
    # STEP 6 - CATEGORY FALLBACK
    # Lo teniamo separato perché sappiamo che prima qui si bloccava.
    # --------------------------------------------------------
    def category_test():
        session = module.requests.Session()
        try:
            categories = module._category_pages()
            result = []

            for category_url in categories:
                try:
                    response = session.get(
                        category_url,
                        headers=module.HEADERS,
                        timeout=5,
                    )
                    result.append({
                        "url": category_url,
                        "status": response.status_code,
                        "bytes": len(response.content),
                    })
                except Exception as exc:
                    result.append({
                        "url": category_url,
                        "error": f"{type(exc).__name__}: {exc}",
                    })

            return {
                "category_count": len(categories),
                "categories": result,
            }
        finally:
            session.close()

    report["steps"].append(
        timed_call(
            "6_category_pages",
            category_test,
            timeout=15,
        )
    )

    # --------------------------------------------------------
    # STEP 7 - _discover COMPLETO
    # --------------------------------------------------------
    def discover_test():
        session = module.requests.Session()
        try:
            urls = module._discover(session, query)
            return {
                "count": len(urls),
                "urls": urls[:30],
            }
        finally:
            session.close()

    report["steps"].append(
        timed_call(
            "7_discover_complete",
            discover_test,
            timeout=20,
        )
    )

    # --------------------------------------------------------
    # STEP 8 - search() COMPLETO
    # --------------------------------------------------------
    report["steps"].append(
        timed_call(
            "8_search_complete",
            lambda: module.search(query),
            timeout=25,
        )
    )

    # --------------------------------------------------------
    # STEP 9 - interpretazione automatica
    # --------------------------------------------------------
    interpretation = []

    direct_ok_with_candidates = any(
        s.get("status") == "ok"
        and isinstance(s.get("value"), dict)
        and s["value"].get("candidate_count", 0) > 0
        for s in report["steps"]
        if str(s.get("step", "")).startswith("4_direct_route_")
    )

    direct_ok_no_candidates = any(
        s.get("status") == "ok"
        and isinstance(s.get("value"), dict)
        and s["value"].get("candidate_count", 0) == 0
        for s in report["steps"]
        if str(s.get("step", "")).startswith("4_direct_route_")
    )

    if direct_ok_with_candidates:
        interpretation.append(
            "Deloox restituisce URL prodotto dalla ricerca diretta. "
            "Se search() restituisce 0, il problema è dopo la discovery: "
            "validazione _product() o filtro del risultato."
        )

    if direct_ok_no_candidates:
        interpretation.append(
            "Le route di ricerca diretta rispondono ma non producono "
            "URL /product/. Bisogna capire quale endpoint di ricerca "
            "Deloox restituisce realmente i prodotti."
        )

    if any(
        s.get("status") == "TIMEOUT"
        for s in report["steps"]
        if str(s.get("step", "")).startswith("4_direct_route_")
    ):
        interpretation.append(
            "Almeno una route diretta va in timeout."
        )

    report["interpretation"] = interpretation
    return report
