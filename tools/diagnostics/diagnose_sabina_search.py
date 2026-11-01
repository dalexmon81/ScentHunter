"""
ScentHunter - Sabina direct search() forensic diagnostic.

Read-only diagnostic. Calls only the deployed Sabina scraper's search(query)
function. It does not call ProductMatcher, catalog, hydration, aggregation,
or the normal production search job.

Purpose: determine whether discovery candidates are being converted into
product rows by search().
"""

import inspect
import time

from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/diagnose-sabina-search")
def diagnose_sabina_search(
    q: str = Query("Liquid Brun", min_length=1, max_length=120),
):
    started = time.monotonic()

    try:
        from scrapers.sabina import scraper

        discover = getattr(scraper, "discover_product_urls", None)
        search = getattr(scraper, "search", None)

        if not callable(discover) or not callable(search):
            return {
                "diagnostic": "sabina-search-v1",
                "ok": False,
                "error": "Sabina discover_product_urls/search not available",
                "read_only": True,
            }

        session = scraper.requests.Session()

        try:
            discovery_started = time.monotonic()
            candidate_urls = discover(session, q)
            discovery_elapsed = time.monotonic() - discovery_started
        finally:
            session.close()

        candidates = list(candidate_urls or [])

        # Now call the real deployed search() exactly once. This deliberately
        # exercises its own discovery path again, but does not invoke matcher
        # or production aggregation.
        search_started = time.monotonic()
        rows = search(q)
        search_elapsed = time.monotonic() - search_started

        compact_rows = []
        for row in (rows or []):
            compact_rows.append({
                "name": row.get("name"),
                "brand": row.get("brand"),
                "size_ml": row.get("size_ml"),
                "price": row.get("price"),
                "availability": row.get("availability"),
                "available": row.get("available"),
                "url": row.get("url"),
                "identity": row.get("identity"),
            })

        return {
            "diagnostic": "sabina-search-v1",
            "ok": True,
            "query": q,
            "scraper_module": getattr(scraper, "__file__", None),
            "search_source": inspect.getsource(search),
            "discovery": {
                "candidate_count": len(candidates),
                "candidates": candidates,
                "elapsed_sec": round(discovery_elapsed, 3),
            },
            "search": {
                "row_count": len(rows or []),
                "rows": compact_rows,
                "elapsed_sec": round(search_elapsed, 3),
            },
            "read_only": True,
            "product_matcher_called": False,
            "catalog_written": False,
            "hydration_called": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }

    except Exception as exc:
        return {
            "diagnostic": "sabina-search-v1",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "read_only": True,
            "product_matcher_called": False,
            "catalog_written": False,
            "hydration_called": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }
