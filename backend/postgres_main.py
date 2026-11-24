"""PostgreSQL-only ScentHunter web application."""
from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.catalog_search import router as catalog_search_router

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
    """Send visitors to the UI that is wired to the PostgreSQL catalog API."""
    return RedirectResponse(url="/catalog-demo", status_code=307)
