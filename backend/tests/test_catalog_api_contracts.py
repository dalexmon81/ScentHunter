from fastapi import HTTPException
import pytest

from app.api.admin import _authorize, router as admin_router
from app.api.catalog_resources import router as resources_router
from app.api.catalog_search import router as search_router
from app.api.offer_refresh import router as offer_refresh_router
from app.schemas.catalog import SearchResponse


def test_catalog_search_response_contract_accepts_ranked_products():
    payload = {
        "query": "Dior Sauvage", "count": 1, "offer_count": 1,
        "message": None, "suggestions": [], "limit": 30, "offset": 0,
        "results": [{
            "brand": "Dior", "brand_slug": "dior",
            "fragrance": "Sauvage", "fragrance_slug": "sauvage",
            "family": "aromatic", "gender": "men", "olfactory_notes": ["bergamot"],
            "variants": [{
                "variant_id": "variant-1", "canonical_key": "dior|sauvage|edp|100",
                "concentration": "EDP", "size_ml": 100, "format": {"tester": False},
                "offers": [{
                    "offer_id": "offer-1", "store": "notino", "country": "FR",
                    "price": "79.90", "currency": "EUR", "availability": "in_stock",
                    "url": "https://example.test/item", "captured_at": "2026-11-04T10:00:00Z",
                    "shipping_cost": None, "score": 91.5,
                    "score_breakdown": {
                        "price": 30, "store_reliability": 18, "freshness": 14,
                        "availability": 15, "match_quality": 14, "shipping_transparency": 1,
                        "penalties": 0,
                    },
                    "landed_price": None, "verify_price": False, "warning": None,
                }],
                "min_price_by_currency": {"EUR": "79.90"},
                "min_price": "79.90", "store_count": 1, "availability": "in_stock",
            }],
            "variant_selection_required": False, "offer_count": 1,
        }],
    }
    result = SearchResponse.model_validate(payload)
    assert result.results[0].variants[0].offers[0].score == 91.5


def test_admin_api_requires_configured_bearer_token(monkeypatch):
    monkeypatch.delenv("SCENTHUNTER_ADMIN_TOKEN", raising=False)
    with pytest.raises(HTTPException) as exc:
        _authorize("Bearer invalid")
    assert exc.value.status_code == 503
    monkeypatch.setenv("SCENTHUNTER_ADMIN_TOKEN", "test-secret")
    with pytest.raises(HTTPException) as exc:
        _authorize("Bearer wrong")
    assert exc.value.status_code == 401
    assert _authorize("Bearer test-secret") is None


def test_api_router_namespaces_are_mounted_as_expected():
    search_paths = {route.path for route in search_router.routes}
    resource_paths = {route.path for route in resources_router.routes}
    admin_paths = {route.path for route in admin_router.routes}
    refresh_paths = {route.path for route in offer_refresh_router.routes}
    assert "/api/search" in search_paths
    assert "/api/products/{slug}" in resource_paths
    assert "/api/products/{slug}/offers" in resource_paths
    assert "/api/brands" in resource_paths
    assert "/api/stores" in resource_paths
    assert "/api/offers" in resource_paths
    assert "/api/admin/connectors" in admin_paths
    assert "/api/admin/ingestion" in admin_paths
    assert "/api/admin/matching" in admin_paths
    assert "/api/offers/{offer_id}/refresh" in refresh_paths
