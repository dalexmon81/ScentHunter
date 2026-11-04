"""Read-only bridge from legacy product IDs to persisted Phase 2 offers."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.db import make_session_factory
from app.models import LegacyProductIdMap, Offer, ProductVariant, Store

router = APIRouter()


def legacy_product_offers(legacy_product_id: str, *, session_factory=None):
    """Resolve a legacy catalog ID through the explicit migration map only."""
    key = str(legacy_product_id or "").strip()
    if not key or len(key) > 80:
        raise HTTPException(status_code=400, detail="invalid_legacy_product_id")

    factory = session_factory or make_session_factory()
    try:
        with factory() as session:
            rows = session.execute(
                select(
                    Offer.id,
                    Store.slug,
                    Offer.url,
                    Offer.price,
                    Offer.currency,
                    Offer.availability,
                    Offer.captured_at,
                    ProductVariant.size_ml,
                )
                .join(Store, Offer.store_id == Store.id)
                .join(ProductVariant, Offer.product_variant_id == ProductVariant.id)
                .join(
                    LegacyProductIdMap,
                    LegacyProductIdMap.fragrance_id == ProductVariant.fragrance_id,
                )
                .where(
                    LegacyProductIdMap.legacy_product_id == key,
                    Offer.status == "active",
                    Store.status == "active",
                )
                .order_by(Offer.price.asc(), Store.slug.asc())
            ).all()
            return {
                "legacy_product_id": key,
                "offers": [
                    {
                        "phase2_offer_id": str(row.id),
                        "store": row.slug,
                        "url": row.url,
                        "price": float(row.price),
                        "currency": row.currency,
                        "availability": row.availability,
                        "captured_at": row.captured_at.isoformat() if row.captured_at else None,
                        "size_ml": row.size_ml,
                    }
                    for row in rows
                ],
            }
    finally:
        factory.kw["bind"].dispose()


@router.get("/catalog/legacy-products/{legacy_product_id}/offers")
def get_legacy_product_offers(legacy_product_id: str):
    """Return only active Phase 2 offers explicitly mapped to this legacy ID."""
    return legacy_product_offers(legacy_product_id)
