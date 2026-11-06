"""Read-only catalog search backed exclusively by persisted canonical identities.

This endpoint never calls retailer connectors or performs live store searches.
"""
from __future__ import annotations

from sqlalchemy import and_, or_, select

from fastapi import APIRouter, HTTPException, Query

from app.db import make_session_factory
from app.models import Brand, Fragrance, Offer, ProductVariant, Store

router = APIRouter()


def search_catalog(query: str, *, limit: int = 20, session_factory=None):
    """Search canonical brand/fragrance identities and attach persisted offers."""
    term = str(query or "").strip()
    if len(term) < 2 or len(term) > 120:
        raise HTTPException(status_code=400, detail="invalid_search_query")
    if not 1 <= limit <= 30:
        raise HTTPException(status_code=400, detail="invalid_search_limit")

    factory = session_factory or make_session_factory()
    try:
        with factory() as session:
            matching_ids = (
                select(Fragrance.id)
                .join(Brand, Brand.id == Fragrance.brand_id)
                .where(
                    or_(
                        Fragrance.name.ilike(f"%{term}%"),
                        Brand.name.ilike(f"%{term}%"),
                    )
                )
                .order_by(Brand.name.asc(), Fragrance.name.asc())
                .limit(limit)
                .subquery()
            )

            rows = session.execute(
                select(
                    Brand.name.label("brand_name"),
                    Fragrance.id.label("fragrance_id"),
                    Fragrance.name.label("fragrance_name"),
                    Fragrance.gender,
                    Fragrance.family,
                    ProductVariant.id.label("variant_id"),
                    ProductVariant.canonical_key,
                    ProductVariant.concentration,
                    ProductVariant.size_ml,
                    ProductVariant.is_tester,
                    ProductVariant.is_refill,
                    ProductVariant.is_gift_set,
                    Offer.id.label("offer_id"),
                    Offer.url,
                    Offer.price,
                    Offer.currency,
                    Offer.availability,
                    Offer.captured_at,
                    Store.slug.label("store_slug"),
                )
                .join(Brand, Brand.id == Fragrance.brand_id)
                .outerjoin(ProductVariant, ProductVariant.fragrance_id == Fragrance.id)
                .outerjoin(
                    Offer,
                    and_(
                        Offer.product_variant_id == ProductVariant.id,
                        Offer.status == "active",
                    ),
                )
                .outerjoin(
                    Store,
                    and_(Store.id == Offer.store_id, Store.status == "active"),
                )
                .where(Fragrance.id.in_(select(matching_ids.c.id)))
                .order_by(
                    Brand.name.asc(),
                    Fragrance.name.asc(),
                    ProductVariant.size_ml.asc().nulls_last(),
                    Offer.price.asc().nulls_last(),
                )
            ).all()

            products = {}
            for row in rows:
                key = str(row.fragrance_id)
                product = products.setdefault(
                    key,
                    {
                        "brand": row.brand_name,
                        "fragrance": row.fragrance_name,
                        "gender": row.gender,
                        "family": row.family,
                        "variants": {},
                    },
                )
                if row.variant_id is None:
                    continue
                variant_key = str(row.variant_id)
                variant = product["variants"].setdefault(
                    variant_key,
                    {
                        "variant_id": variant_key,
                        "canonical_key": row.canonical_key,
                        "concentration": row.concentration,
                        "size_ml": row.size_ml,
                        "is_tester": row.is_tester,
                        "is_refill": row.is_refill,
                        "is_gift_set": row.is_gift_set,
                        "offers": [],
                    },
                )
                # A missing/inactive store must never make an offer visible.
                if row.offer_id is not None and row.store_slug is not None:
                    variant["offers"].append(
                        {
                            "offer_id": str(row.offer_id),
                            "store": row.store_slug,
                            "url": row.url,
                            "price": float(row.price),
                            "currency": row.currency,
                            "availability": row.availability,
                            "captured_at": (
                                row.captured_at.isoformat()
                                if row.captured_at
                                else None
                            ),
                        }
                    )

            result = []
            for product in products.values():
                product["variants"] = list(product["variants"].values())
                result.append(product)
            return {"query": term, "count": len(result), "results": result}
    finally:
        factory.kw["bind"].dispose()


@router.get("/catalog/search")
def get_catalog_search(
    q: str = Query(..., min_length=2, max_length=120),
    limit: int = Query(20, ge=1, le=30),
):
    """Search canonical catalog records and already-published offers only."""
    return search_catalog(q, limit=limit)
