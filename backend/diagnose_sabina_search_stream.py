"""
ScentHunter - Sabina/catalog coverage diagnostics.

Read-only scraper diagnostics plus one explicitly operational coverage runner.
The coverage runner is generic: it accepts a store + canonical product_id,
uses the existing catalog_coverage machinery, and does not contain any
product-specific URL or identity rule.
"""

import time
from fastapi import APIRouter, Query
import requests

router = APIRouter()

TARGET_41708 = (
    "https://www.sabina.com/es/perfumes-mujer/"
    "41708-liquid-brun-limited-edition-extrait-de-parfum.html"
)


@router.get("/diagnose-sabina-search-stream")
def diagnose_sabina_search_stream(
    q: str = Query("Liquid Brun", min_length=1, max_length=120),
):
    started = time.monotonic()

    try:
        from scrapers.sabina import scraper

        stream = getattr(scraper, "search_stream", None)
        if not callable(stream):
            return {
                "diagnostic": "sabina-search-stream-v1",
                "ok": False,
                "error": "search_stream not available",
                "read_only": True,
            }

        returned = stream(q)

        result_rows = []
        if isinstance(returned, dict):
            value = returned.get("results")
            if isinstance(value, list):
                result_rows = value

        compact = []
        for row in result_rows:
            if isinstance(row, dict):
                compact.append({
                    "name": row.get("name"),
                    "brand": row.get("brand"),
                    "price": row.get("price"),
                    "availability": row.get("availability"),
                    "available": row.get("available"),
                    "url": row.get("url"),
                    "identity": row.get("identity"),
                })

        return {
            "diagnostic": "sabina-search-stream-v1",
            "ok": True,
            "query": q,
            "return_type": type(returned).__name__,
            "return": {
                "status": returned.get("status") if isinstance(returned, dict) else None,
                "verified": returned.get("verified") if isinstance(returned, dict) else None,
                "error": returned.get("error") if isinstance(returned, dict) else None,
                "details": returned.get("details") if isinstance(returned, dict) else None,
                "results_count": len(result_rows),
                "results": compact,
            },
            "read_only": True,
            "product_matcher_called": False,
            "catalog_written": False,
            "hydration_called": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }

    except Exception as exc:
        return {
            "diagnostic": "sabina-search-stream-v1",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "read_only": True,
            "product_matcher_called": False,
            "catalog_written": False,
            "hydration_called": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }


@router.get("/diagnose-sabina-product-page")
def diagnose_sabina_product_page(
    url: str = Query(TARGET_41708, min_length=20, max_length=500),
    q: str = Query("Liquid Brun Limited Edition", min_length=1, max_length=120),
):
    """
    Read-only transport/parser isolation test.

    Fetches exactly one supplied Sabina product URL with requests and then
    runs the production extract_product_page parser. No search, matcher,
    catalog write, or hydration is called.
    """
    started = time.monotonic()

    try:
        from scrapers.sabina import scraper

        session = requests.Session()
        try:
            response = session.get(
                url,
                headers=scraper.HEADERS,
                timeout=scraper.TIMEOUT,
                allow_redirects=True,
            )

            transport = {
                "status_code": response.status_code,
                "final_url": response.url,
                "bytes": len(response.content or b""),
                "elapsed_sec": round(time.monotonic() - started, 3),
            }

            parsed = None
            parse_error = None
            if response.status_code < 400:
                try:
                    parsed = scraper.extract_product_page(session, url, q)
                except Exception as exc:
                    parse_error = f"{type(exc).__name__}: {exc}"

            compact = None
            if isinstance(parsed, dict):
                compact = {
                    "name": parsed.get("name"),
                    "brand": parsed.get("brand"),
                    "price": parsed.get("price"),
                    "available": parsed.get("available"),
                    "availability": parsed.get("availability"),
                    "url": parsed.get("url"),
                    "identity": parsed.get("identity"),
                    "attributes": parsed.get("attributes"),
                    "offer": parsed.get("offer"),
                    "provenance": parsed.get("provenance"),
                }

            return {
                "diagnostic": "sabina-product-page-v1",
                "ok": True,
                "query": q,
                "url": url,
                "transport": transport,
                "parser": {
                    "returned_product": parsed is not None,
                    "parse_error": parse_error,
                    "product": compact,
                },
                "read_only": True,
                "product_matcher_called": False,
                "catalog_written": False,
                "hydration_called": False,
                "elapsed_sec": round(time.monotonic() - started, 3),
            }
        finally:
            session.close()

    except Exception as exc:
        return {
            "diagnostic": "sabina-product-page-v1",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "read_only": True,
            "product_matcher_called": False,
            "catalog_written": False,
            "hydration_called": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }


@router.get("/diagnose-sabina-discover-and-target")
def diagnose_sabina_discover_and_target(
    q: str = Query("Liquid Brun Limited Edition", min_length=1, max_length=120),
):
    """
    Read-only isolation of production discovery + the exact discovered target.
    It intentionally does NOT run search() over every candidate.
    """
    started = time.monotonic()
    target_token = "41708"

    try:
        from scrapers.sabina import scraper

        session = requests.Session()
        try:
            discovery_started = time.monotonic()
            candidates = scraper.discover_product_urls(session, q)
            discovery_elapsed = round(time.monotonic() - discovery_started, 3)

            target_urls = [
                url for url in candidates
                if target_token in str(url)
            ]

            target_result = None
            target_error = None

            if target_urls:
                target_url = target_urls[0]
                parse_started = time.monotonic()
                try:
                    target_result = scraper.extract_product_page(
                        session, target_url, q
                    )
                except Exception as exc:
                    target_error = f"{type(exc).__name__}: {exc}"
                parse_elapsed = round(time.monotonic() - parse_started, 3)
            else:
                target_url = None
                parse_elapsed = None

            compact = None
            if isinstance(target_result, dict):
                compact = {
                    "name": target_result.get("name"),
                    "brand": target_result.get("brand"),
                    "price": target_result.get("price"),
                    "available": target_result.get("available"),
                    "availability": target_result.get("availability"),
                    "url": target_result.get("url"),
                    "identity": target_result.get("identity"),
                    "attributes": target_result.get("attributes"),
                    "offer": target_result.get("offer"),
                }

            return {
                "diagnostic": "sabina-discover-and-target-v1",
                "ok": True,
                "query": q,
                "discovery": {
                    "elapsed_sec": discovery_elapsed,
                    "candidate_count": len(candidates),
                    "candidates": candidates,
                    "target_41708_found": bool(target_urls),
                    "target_urls": target_urls,
                },
                "target_parse": {
                    "url": target_url,
                    "elapsed_sec": parse_elapsed,
                    "returned_product": target_result is not None,
                    "error": target_error,
                    "product": compact,
                },
                "read_only": True,
                "production_search_called": False,
                "product_matcher_called": False,
                "catalog_written": False,
                "hydration_called": False,
                "elapsed_sec": round(time.monotonic() - started, 3),
            }
        finally:
            session.close()

    except Exception as exc:
        return {
            "diagnostic": "sabina-discover-and-target-v1",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "read_only": True,
            "production_search_called": False,
            "product_matcher_called": False,
            "catalog_written": False,
            "hydration_called": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }


@router.get("/diagnose-catalog-coverage-run")
def diagnose_catalog_coverage_run(
    store: str = Query("sabina", min_length=1, max_length=40),
    product_id: str = Query(..., min_length=1, max_length=120),
):
    """
    Explicitly advance one generic store x canonical-product coverage task.

    Unlike the other diagnostics this endpoint is intentionally operational:
    it may persist a discovered retailer URL into store_urls/hydration_queue
    and update the corresponding catalog_coverage state. It uses only the
    canonical product_id supplied by the caller and the existing generic
    coverage engine. No product-specific URL, name, or rule is embedded.
    """
    started = time.monotonic()
    store_key = str(store or "").strip().lower()
    product_key = str(product_id or "").strip()

    try:
        from catalog_engine import (
            _coverage_ensure_schema,
            _coverage_load_catalog,
            _coverage_run_task,
            _coverage_finish_task,
        )

        _coverage_ensure_schema()
        products = _coverage_load_catalog()

        product = next(
            (
                p for p in products
                if str(p.get("product_id") or "").strip() == product_key
            ),
            None,
        )

        if product is None:
            return {
                "diagnostic": "catalog-coverage-run-v1",
                "ok": False,
                "error": "canonical_product_not_found",
                "store": store_key,
                "product_id": product_key,
                "catalog_written": False,
                "elapsed_sec": round(time.monotonic() - started, 3),
            }

        task = {
            "store": store_key,
            "product": product,
            "attempts": 0,
        }

        result = _coverage_run_task(task)
        _coverage_finish_task(task, result)

        return {
            "diagnostic": "catalog-coverage-run-v1",
            "ok": True,
            "store": store_key,
            "product_id": product_key,
            "canonical_name": product.get("canonical_name"),
            "coverage_queries": (
                __import__("catalog_engine")._coverage_queries(product)
            ),
            "result": result,
            "catalog_written": bool(result.get("found")),
            "hydration_called": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }

    except Exception as exc:
        return {
            "diagnostic": "catalog-coverage-run-v1",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "store": store_key,
            "product_id": product_key,
            "catalog_written": False,
            "hydration_called": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }
