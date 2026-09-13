from __future__ import annotations

from fastapi import APIRouter, Query

from scrapers.notino.scraper import diagnose

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/notino")
def debug_notino(q: str = Query(..., min_length=2)):
    """Run the full Notino root-cause diagnostic.

    IMPORTANT: this endpoint intentionally calls diagnose(), never search().
    The response therefore cannot silently become {count: 0, items: []}.
    """
    return diagnose(q)
