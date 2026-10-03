"""
ScentHunter - Sabina search_stream contract diagnostic.

Read-only: calls only Sabina search_stream(query), then reports the exact
return contract and whether its results list contains product rows.
"""

import time
from fastapi import APIRouter, Query

router = APIRouter()


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
