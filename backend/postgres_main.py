"""PostgreSQL-only ScentHunter web application."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from app.api.catalog_search import router as catalog_search_router

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_INDEX = ROOT / "frontend" / "index.html"

app = FastAPI(title="ScentHunter API", version="6.0-postgresql-only")
app.include_router(catalog_search_router)


@app.get("/health")
def health():
    return JSONResponse({
        "status": "healthy",
        "architecture": "postgresql-catalog-only",
        "public_search": "/api/catalog/search",
    })


@app.get("/", include_in_schema=False)
@app.get("/frontend", include_in_schema=False)
def frontend():
    return FileResponse(FRONTEND_INDEX)
