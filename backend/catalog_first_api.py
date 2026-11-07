"""Isolated catalog-first HTTP application.

This app serves the existing frontend against PostgreSQL-backed canonical
search only. It deliberately does not import the legacy scraper application,
start retailer discovery, or run retailer HTTP requests during user searches.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import text

from app.db import make_engine
from app.api.catalog_search import router as catalog_search_router
from app.api.legacy_catalog import router as legacy_catalog_router
from app.api.offer_refresh import router as offer_refresh_router
from app.services.catalog_search import search_catalog_for_frontend


app = FastAPI(
    title="ScentHunter Catalog-first API",
    version="1.0.0-staging",
    description="PostgreSQL-only product search and published-offer API.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(catalog_search_router)
app.include_router(legacy_catalog_router)
app.include_router(offer_refresh_router)

_FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "index.html"


@app.get("/", include_in_schema=False)
@app.get("/frontend", include_in_schema=False)
def frontend() -> FileResponse:
    """Serve the current ScentHunter UI from the same staging origin."""
    if not _FRONTEND.is_file():
        raise HTTPException(status_code=503, detail="frontend_bundle_unavailable")
    return FileResponse(_FRONTEND)


@app.get("/healthz")
def healthz() -> dict:
    """Verify the API process can open its configured catalog database."""
    engine = make_engine()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            return {
                "ok": True,
                "service": "catalog-first-api",
                "database_dialect": engine.dialect.name,
            }
    finally:
        engine.dispose()


@app.get("/search-start")
def search_start(
    q: str = Query(..., min_length=2, max_length=120),
) -> dict:
    """Return a completed frontend search from persisted catalog data only."""
    try:
        payload = search_catalog_for_frontend(q)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        **payload,
        "catalog_rollout": {
            "mode": "catalog",
            "environment": "staging",
            "traffic_percent": 100,
        },
    }
