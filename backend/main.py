from fastapi import FastAPI, HTTPException
import importlib
import inspect
import json
import time
import traceback
import requests
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

app = FastAPI(title="ScentHunter - Deloox REAL Diagnostic", version="2.5")

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


    # 7. Identify exactly which discovery source produces the candidate URLs.
    # This is diagnostic-only: no scraper code is changed.
    try:
        session = scraper.requests.Session()
        source_report = []

        # 7A. Deloox internal search endpoints
        candidate_queries = candidate_fn(query) if callable(candidate_fn) else [query]
        search_endpoints = (
            "/en/search?query=",
            "/en/search?search=",
            "/en/search?q=",
        )
        search_sources = []
        for dq in candidate_queries[:6]:
            for route in search_endpoints:
                endpoint = scraper.BASE_URL + route + scraper.quote_plus(dq)
                try:
                    rr = session.get(endpoint, headers=scraper.HEADERS, timeout=scraper.TIMEOUT)
                    urls = scraper._candidate_product_urls(
                        rr.text,
                        query,
                        discovery_query=dq,
                        accept_all_products=True,
                    ) if rr.status_code < 400 else []
                    search_sources.append({
                        "query": dq,
                        "endpoint": endpoint,
                        "http_status": rr.status_code,
                        "candidate_count": len(urls),
                        "candidate_urls": urls[:20],
                    })
                except Exception as exc:
                    search_sources.append({
                        "query": dq,
                        "endpoint": endpoint,
                        "error": f"{type(exc).__name__}: {exc}",
                    })

        source_report.append({
            "source": "internal_search_endpoints",
            "checks": search_sources,
        })

        # 7B. Product sitemaps
        try:
            sitemap_urls = scraper._sitemap_product_urls(
                session, query, max_sitemaps=12, max_urls=80
            )
            source_report.append({
                "source": "product_sitemaps",
                "count": len(sitemap_urls),
                "urls": sitemap_urls[:30],
            })
        except Exception as exc:
            source_report.append({
                "source": "product_sitemaps",
                "error": f"{type(exc).__name__}: {exc}",
            })

        # 7C. Category discovery
        try:
            category_urls = scraper._discover_from_categories(
                session, query, max_urls=80
            )
            source_report.append({
                "source": "categories",
                "count": len(category_urls),
                "urls": category_urls[:30],
            })
        except Exception as exc:
            source_report.append({
                "source": "categories",
                "error": f"{type(exc).__name__}: {exc}",
            })

        # 7D. Legacy Italian search endpoint
        try:
            endpoint = scraper.BASE_URL + "/it/cerca?query=" + scraper.quote_plus(query)
            rr = session.get(endpoint, headers=scraper.HEADERS, timeout=scraper.TIMEOUT)
            urls = scraper._candidate_product_urls(
                rr.text, query, accept_all_products=True
            ) if rr.status_code < 400 else []
            source_report.append({
                "source": "legacy_it_search",
                "http_status": rr.status_code,
                "candidate_count": len(urls),
                "candidate_urls": urls[:30],
            })
        except Exception as exc:
            source_report.append({
                "source": "legacy_it_search",
                "error": f"{type(exc).__name__}: {exc}",
            })

        report["steps"].append({
            "step": "7_discovery_source_attribution",
            "status": "OK",
            "value": source_report,
        })
        session.close()
    except Exception as exc:
        report["steps"].append({
            "step": "7_discovery_source_attribution",
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })


    # 8. Test known CURRENT Deloox URLs independently.
    # These URLs are taken from current indexed Deloox pages and are
    # diagnostic-only: no scraper code is changed.
    try:
        session = scraper.requests.Session()

        known_urls = [
            scraper.BASE_URL
            + "/product/1282489/"
            + "rasasi-hawas-for-him-eau-de-parfum-100-ml.html",

            scraper.BASE_URL
            + "/category/1000054/"
            + "mens-fragrances.html",

            scraper.BASE_URL
            + "/it/categoria/1080044/"
            + "rasasi-profumi.html",
        ]

        known_checks = []

        for url in known_urls:
            try:
                rr = session.get(
                    url,
                    headers=scraper.HEADERS,
                    timeout=scraper.TIMEOUT,
                )

                item = None
                if rr.status_code < 400 and "/product/" in url:
                    item = scraper._product(
                        url,
                        rr.text,
                        query,
                    )

                known_checks.append({
                    "url": url,
                    "http_status": rr.status_code,
                    "content_type": rr.headers.get("content-type"),
                    "bytes": len(rr.content),
                    "product_result": (
                        "ACCEPTED"
                        if item
                        else (
                            "REJECTED"
                            if "/product/" in url
                            and rr.status_code < 400
                            else None
                        )
                    ),
                    "product_name": (
                        item.get("name")
                        if item
                        else None
                    ),
                })

            except Exception as exc:
                known_checks.append({
                    "url": url,
                    "error": f"{type(exc).__name__}: {exc}",
                })

        report["steps"].append({
            "step": "8_known_current_urls",
            "status": "OK",
            "value": known_checks,
        })

        session.close()

    except Exception as exc:
        report["steps"].append({
            "step": "8_known_current_urls",
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })


    # 9. Test the proposed discovery fix WITHOUT changing the real scraper.
    # Temporarily replace _category_pages() only in memory with the
    # current Deloox category pages, then run the real discovery code.
    try:
        original_category_pages = getattr(
            scraper,
            "_category_pages",
            None,
        )

        if callable(original_category_pages):
            scraper._category_pages = lambda: (
                scraper.BASE_URL
                + "/category/1000054/mens-fragrances.html",
                scraper.BASE_URL
                + "/category/1075639/womens-fragrances.html",
                scraper.BASE_URL
                + "/en/category/1025540/trending.html?page=60",
            )

            with requests.Session() as test_session:
                proposed_urls = scraper._discover_from_categories(
                    test_session,
                    query,
                    max_urls=24,
                )

            report["steps"].append({
                "step": "9_proposed_current_category_discovery",
                "status": "OK",
                "value": {
                    "category_pages_tested": [
                        scraper.BASE_URL
                        + "/category/1000054/mens-fragrances.html",
                        scraper.BASE_URL
                        + "/category/1075639/womens-fragrances.html",
                        scraper.BASE_URL
                        + "/en/category/1025540/trending.html?page=60",
                    ],
                    "discovered_count": len(proposed_urls),
                    "urls": proposed_urls[:24],
                },
            })

            scraper._category_pages = original_category_pages
        else:
            report["steps"].append({
                "step": "9_proposed_current_category_discovery",
                "status": "ERROR",
                "error": "_category_pages not available",
            })

    except Exception as exc:
        try:
            if callable(original_category_pages):
                scraper._category_pages = original_category_pages
        except Exception:
            pass

        report["steps"].append({
            "step": "9_proposed_current_category_discovery",
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })

    report["diagnosis"] = (
        "4_real_search chiama direttamente search(). "
        "Lo step 6 separa discovery, download pagina e _product(): "
        "se gli URL vengono scoperti ma _product() li rifiuta, "
        "il punto di perdita è la validazione del prodotto."
    )

    return report
