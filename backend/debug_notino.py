from fastapi import APIRouter, Query
from backend.scrapers.notino.scraper import search as notino_search

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/notino")
def debug_notino(q: str = Query(..., min_length=2)):
    items = notino_search(q)
    return {
        "query": q,
        "count": len(items),
        "items": items[:20],
    }
