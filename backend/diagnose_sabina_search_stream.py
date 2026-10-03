"""
ScentHunter - Sabina search/product diagnostics.

Read-only diagnostics. No matcher, catalog write, or hydration.
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
