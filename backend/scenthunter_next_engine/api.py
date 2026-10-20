"""Optional FastAPI adapter for the isolated next engine.

Mount this router only behind an explicit feature flag and configure a separate
SCENTHUNTER_NEXT_DB path. Importing this module does not open the database.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any

from .repository import SQLiteOfferRepository
from .search import SearchRequest, SearchService
from .telemetry import metrics

try:
    from fastapi import APIRouter, HTTPException, Query
except ImportError:  # Core package and tests remain standard-library only.
    APIRouter = None


def create_router(db_path: str | Path | None = None):
    if APIRouter is None:
        raise RuntimeError("FastAPI is required to create the next-engine API router")
    if db_path is None:
        from .runtime import validated_database_path
        path = validated_database_path()
    else:
        path = Path(db_path).expanduser().resolve()
        # A configured legacy path is a hard stop, not a warning.
        legacy_path = (os.environ.get("SCENTHUNTER_LEGACY_DB") or os.environ.get("SCENTHUNTER_CATALOG_DB", "")).strip()
        if legacy_path and path == Path(legacy_path).expanduser().resolve():
            raise RuntimeError("next-engine database must not be the legacy catalog database")

    repository = SQLiteOfferRepository(path)
    search_service = SearchService(repository)
    router = APIRouter(prefix="/v2", tags=["next-engine"])

    @router.get("/health")
    def health() -> dict[str, Any]:
        counts = repository.counts()
        return {"ok": True, "engine": "next", "database": "separate",
                "counts": counts}

    @router.get("/metrics")
    def engine_metrics() -> dict[str, Any]:
        # No URL, query, or user-level labels are exposed in this endpoint.
        return {"engine": "next", **metrics.snapshot()}

    @router.get("/search")
    def search(q: str = Query(default="", max_length=200),
               store: str | None = Query(default=None, max_length=64),
               currency: str | None = Query(default=None, min_length=3, max_length=3),
               limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
        try:
            request = SearchRequest(query=q, store=store, currency=currency, limit=limit)
            return search_service.search(request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router
