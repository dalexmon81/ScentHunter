"""PostgreSQL integration tests for the catalog-only search API."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.catalog_search import router as catalog_search_router
from app.db import make_engine


def test_catalog_search_reads_seeded_identity_without_retailer_search():
    engine = make_engine()
    assert engine.dialect.name == "postgresql"
    api = FastAPI()
    api.include_router(catalog_search_router)
    try:
        with TestClient(api) as client:
            response = client.get("/catalog/search", params={"q": "Sauvage"})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["query"] == "Sauvage"
        assert payload["count"] >= 1
        product = next(
            row for row in payload["results"]
            if row["brand"].lower() == "dior"
            and row["fragrance"].lower() == "sauvage"
        )
        assert any(
            variant["size_ml"] == 100
            and (variant["concentration"] or "").lower() in {"edp", "eau de parfum"}
            for variant in product["variants"]
        )
    finally:
        engine.dispose()


def test_catalog_search_rejects_too_short_query():
    engine = make_engine()
    try:
        from app.api.catalog_search import search_catalog
        from fastapi import HTTPException
        try:
            search_catalog(" ")
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("blank search query should be rejected")
    finally:
        engine.dispose()
