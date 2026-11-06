"""HTTP adapter for read-only canonical catalog search.

The API layer validates HTTP input and delegates the catalog use case to services.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.catalog_search import (
    search_catalog as _search_catalog,
    search_catalog_for_frontend,
)

router = APIRouter()


def search_catalog(query: str, *, limit: int = 20, session_factory=None):
    """Compatibility adapter preserving the existing API import contract."""
    try:
        return _search_catalog(query, limit=limit, session_factory=session_factory)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/catalog/search")
def get_catalog_search(
    q: str = Query(..., min_length=2, max_length=120),
    limit: int = Query(20, ge=1, le=30),
):
    """Search canonical catalog records and already-published offers only."""
    return search_catalog(q, limit=limit)
