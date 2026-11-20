"""Isolated read-only catalog-first demo app.

This entrypoint deliberately excludes the legacy scraper/search runtime and its
startup discovery loops. It exposes only the canonical catalog demo and health
check so the staging service cannot accidentally trigger retailer crawling.
"""
from fastapi import FastAPI

from app.api.catalog_search import router as catalog_search_router

app = FastAPI(
    title="ScentHunter Catalog Demo",
    version="catalog-first-preview",
    description="Read-only preview of the canonical fragrance catalog.",
)
app.include_router(catalog_search_router)


@app.get("/health")
def health():
    return {"status": "healthy", "mode": "read-only-catalog-demo"}
