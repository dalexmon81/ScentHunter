"""
ScentHunter temporary Notino diagnostic entrypoint.

Use this file only for the diagnostic deployment. It imports the real
backend.main application unchanged and adds diagnostic JSON endpoints.
After testing, restore the normal main.py.
"""

import importlib
import inspect
import json
import traceback
from typing import Any

from fastapi import Query

from main import app


def _load_notino():
    return importlib.import_module("scrapers.notino.scraper")


def _call_diagnostic(module: Any, query: str):
    candidates = (
        "diagnose",
        "diagnostic",
        "debug_search",
    )

    for name in candidates:
        fn = getattr(module, name, None)
        if callable(fn):
            result = fn(query)
            return {
                "function": name,
                "result": result,
            }

    # Fallback: expose the internal search layers without inventing
    # product-specific logic. This is useful if the scraper has no
    # public diagnose() function.
    report = {
        "function": "fallback",
        "query": query,
        "available_functions": sorted(
            name
            for name, value in inspect.getmembers(module)
            if callable(value) and not name.startswith("__")
        ),
    }

    browser_discover = getattr(module, "browser_discover", None)
    search_http = getattr(module, "_search_http_candidates", None)
    extract_candidates = getattr(module, "extract_candidates_from_html", None)

    report["has_browser_discover"] = callable(browser_discover)
    report["has_http_discovery"] = callable(search_http)
    report["has_candidate_extractor"] = callable(extract_candidates)

    if callable(browser_discover):
        try:
            candidates, browser_report = browser_discover(query)
            report["browser_discovery"] = browser_report
            report["browser_candidates_count"] = len(candidates or [])
            report["browser_candidates"] = [
                {
                    "url": item.get("url"),
                    "context": item.get("context"),
                    "score": item.get("score"),
                }
                for item in (candidates or [])[:100]
                if isinstance(item, dict)
            ]
        except Exception as exc:
            report["browser_discovery_error"] = (
                f"{type(exc).__name__}: {exc}"
            )
            report["browser_discovery_traceback"] = traceback.format_exc()

    return report


@app.get("/diagnose-notino")
def diagnose_notino(
    q: str = Query(..., min_length=1),
):
    query = str(q or "").strip()

    if not query:
        return {
            "ok": False,
            "error": "query vuota",
        }

    try:
        module = _load_notino()
        payload = _call_diagnostic(module, query)

        return {
            "ok": True,
            "store": "notino",
            "query": query,
            **payload,
        }

    except Exception as exc:
        return {
            "ok": False,
            "store": "notino",
            "query": query,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


@app.get("/diagnose-notino-search")
def diagnose_notino_search(
    q: str = Query(..., min_length=1),
):
    """
    Endpoint focused on the normal ScentHunter store path.

    It runs the actual Notino search() function and reports the raw
    scraper output before the global main.py matching layer sees it.
    """
    query = str(q or "").strip()

    try:
        module = _load_notino()
        search_fn = getattr(module, "search", None)

        if not callable(search_fn):
            search_fn = getattr(module, "scrape", None)

        if not callable(search_fn):
            return {
                "ok": False,
                "store": "notino",
                "query": query,
                "error": "Notino scraper has no search()/scrape()",
            }

        raw = search_fn(query)

        return {
            "ok": True,
            "store": "notino",
            "query": query,
            "raw_count": len(raw) if isinstance(raw, list) else 0,
            "raw_results": raw if isinstance(raw, list) else [],
        }

    except Exception as exc:
        return {
            "ok": False,
            "store": "notino",
            "query": query,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
