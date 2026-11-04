"""HTTP contract for catalog-first search; no retailer calls in request handlers."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from time import perf_counter

from fastapi import APIRouter, HTTPException, Query

from app.search.catalog_search import search_catalog
from app.schemas.catalog import SearchResponse
from app.services.observability import record_search_latency

router = APIRouter(prefix="/api", tags=["catalog-search"])


@router.get("/search", response_model=SearchResponse)
def search_products(
    q: str = Query(..., min_length=1, max_length=160),
    brand: str | None = None,
    family: str | None = None,
    gender: str | None = None,
    concentration: str | None = None,
    product_format: str | None = Query(None, alias="format"),
    store: str | None = None,
    availability: str | None = None,
    country: str | None = Query(None, min_length=2, max_length=2),
    currency: str | None = Query(None, min_length=3, max_length=3),
    min_price: Decimal | None = Query(None, ge=0),
    max_price: Decimal | None = Query(None, ge=0),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Search persisted canonical variants and currently published offers."""
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(status_code=400, detail="min_price_exceeds_max_price")
    started_at = perf_counter()
    try:
        return search_catalog(
            q,
            brand=brand,
            family=family,
            gender=gender,
            concentration=concentration,
            product_format=product_format,
            store=store,
            availability=availability,
            country=country,
            currency=currency,
            min_price=min_price,
            max_price=max_price,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        code = str(exc) if str(exc) else "invalid_search_request"
        raise HTTPException(status_code=400, detail=code) from exc
    finally:
        record_search_latency(started_at)
