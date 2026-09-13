from __future__ import annotations

from fastapi import APIRouter, Query

from scrapers.notino.scraper import diagnose, _browser_search

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/notino")
def debug_notino(q: str = Query(..., min_length=2)):
    """Run the full Notino root-cause diagnostic.

    IMPORTANT: this endpoint intentionally calls diagnose(), never search().
    """
    return diagnose(q)


@router.get("/notino-browser")
def debug_notino_browser(q: str = Query(..., min_length=2)):
    """Run ONLY the Playwright Notino discovery path.

    This isolates browser discovery from Bing/Google/Jina and exposes the
    scraper's raw browser candidates plus filtering result.
    """
    candidates, report = _browser_search(q)
    return {
        "diagnostic": True,
        "diagnostic_version": "notino-browser-isolation-2026-09-13-v1",
        "query": q,
        "report": report,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
