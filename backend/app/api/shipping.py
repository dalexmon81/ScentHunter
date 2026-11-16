"""Read-only endpoint for destination-specific shipping quotes."""
from __future__ import annotations

from decimal import Decimal
from fastapi import APIRouter, HTTPException, Query

from app.services.shipping_quotes import quote_store_shipping

router = APIRouter(prefix="/shipping", tags=["shipping"])


@router.get("/quote")
def get_shipping_quote(
    store_slug: str = Query(..., min_length=1, max_length=180),
    country_code: str = Query(..., min_length=2, max_length=2),
    order_subtotal: Decimal = Query(..., ge=0),
    currency: str = Query("EUR", min_length=3, max_length=3),
    postal_code: str | None = Query(None, max_length=24),
    weight_kg: Decimal | None = Query(None, ge=0),
):
    """Quote a single-store order; unknown rates never mean free shipping."""
    try:
        return quote_store_shipping(
            store_slug=store_slug, country_code=country_code,
            order_subtotal=order_subtotal, currency=currency,
            postal_code=postal_code, weight_kg=weight_kg,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
