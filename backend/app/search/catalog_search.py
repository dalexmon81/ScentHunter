"""Catalog-first search against persisted canonical variants and published offers.

PostgreSQL uses native full-text search. SQLite LIKE is retained only for fast
unit tests and local development; neither path contacts retailer websites.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, literal_column, or_, select
from sqlalchemy.orm import Session

from app.db import make_session_factory
from app.models import Brand, Fragrance, Offer, ProductVariant, Store


_FORMAT_FIELDS = {
    "tester": ProductVariant.is_tester,
    "refill": ProductVariant.is_refill,
    "gift_set": ProductVariant.is_gift_set,
    "mini": ProductVariant.is_mini,
}


def search_catalog(
    query: str,
    *,
    session_factory=None,
    brand: str | None = None,
    family: str | None = None,
    gender: str | None = None,
    concentration: str | None = None,
    product_format: str | None = None,
    store: str | None = None,
    availability: str | None = None,
    country: str | None = None,
    currency: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    limit: int = 30,
    offset: int = 0,
    freshness_hours: int = 48,
) -> dict[str, Any]:
    """Search canonical products and their published, fresh offers.

    Only active offers from active stores, explicitly published by the offer
    lifecycle, are visible. Search never invokes a connector or scraper.
    """
    q = str(query or "").strip()
    if not q:
        return {"query": "", "count": 0, "offer_count": 0, "results": []}
    if len(q) > 160:
        raise ValueError("query_too_long")
    if product_format and product_format not in _FORMAT_FIELDS:
        raise ValueError("unsupported_product_format")
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    freshness_hours = max(1, min(int(freshness_hours), 24 * 30))
    factory = session_factory or make_session_factory()
    try:
        with factory() as session:
            dialect = session.get_bind().dialect.name
            stmt = (
                select(Brand, Fragrance, ProductVariant, Offer, Store)
                .join(Fragrance, Fragrance.brand_id == Brand.id)
                .join(ProductVariant, ProductVariant.fragrance_id == Fragrance.id)
                .outerjoin(Offer, and_(
                    Offer.product_variant_id == ProductVariant.id,
                    Offer.status == "active",
                    Offer.publication_status == "published",
                    Offer.availability == "in_stock",
                    Offer.captured_at >= datetime.now(timezone.utc) - timedelta(hours=freshness_hours),
                ))
                .outerjoin(Store, and_(
                    Store.id == Offer.store_id,
                    Store.status == "active",
                ))
            )

            if dialect == "postgresql":
                regconfig = literal_column("'simple'::regconfig")
                brand_vector = func.to_tsvector(regconfig, Brand.name)
                fragrance_vector = func.to_tsvector(regconfig, Fragrance.name)
                # Each token can match either field: "Dior Sauvage" matches
                # brand=Dior plus fragrance=Sauvage.
                token_queries = [func.plainto_tsquery(regconfig, token) for token in q.split() if token]
                for token_query in token_queries:
                    stmt = stmt.where(or_(
                        brand_vector.op("@@")(token_query),
                        fragrance_vector.op("@@")(token_query),
                    ))
                rank = func.ts_rank_cd(brand_vector, func.plainto_tsquery(regconfig, q)) + func.ts_rank_cd(
                    fragrance_vector, func.plainto_tsquery(regconfig, q)
                )
                stmt = stmt.order_by(rank.desc().nullslast(), Offer.price.asc().nullslast(), Store.slug.asc())
            else:
                pattern = f"%{q}%"
                stmt = stmt.where(or_(
                    Brand.name.ilike(pattern),
                    Brand.normalized_name.ilike(pattern),
                    Fragrance.name.ilike(pattern),
                 )).order_by(Offer.price.asc().nullslast(), Store.slug.asc())

            if brand:
                stmt = stmt.where(Brand.normalized_name == brand.strip().casefold())
            if family:
                stmt = stmt.where(Fragrance.family.ilike(family.strip()))
            if gender:
                stmt = stmt.where(Fragrance.gender.ilike(gender.strip()))
            if concentration:
                stmt = stmt.where(ProductVariant.concentration.ilike(concentration.strip()))
            if product_format:
                stmt = stmt.where(_FORMAT_FIELDS[product_format] == True)  # noqa: E712
            if store:
                stmt = stmt.where(Store.slug == store.strip().casefold())
            if availability:
                stmt = stmt.where(Offer.availability == availability.strip().casefold())
            if country:
                stmt = stmt.where(Store.country == country.strip().upper())
            if currency:
                stmt = stmt.where(Offer.currency == currency.strip().upper())
            if min_price is not None:
                stmt = stmt.where(Offer.price >= min_price)
            if max_price is not None:
                stmt = stmt.where(Offer.price <= max_price)

            rows = session.execute(stmt).all()
            grouped: dict[str, dict[str, Any]] = {}
            for brand_row, fragrance_row, variant_row, offer_row, store_row in rows:
                key = str(variant_row.id)
                product = grouped.setdefault(key, {
                    "variant_id": key,
                    "canonical_key": variant_row.canonical_key,
                    "brand": brand_row.name,
                    "brand_slug": brand_row.slug,
                    "fragrance": fragrance_row.name,
                    "fragrance_slug": fragrance_row.slug,
                    "family": fragrance_row.family,
                    "gender": fragrance_row.gender,
                    "concentration": variant_row.concentration,
                    "size_ml": variant_row.size_ml,
                    "format": {
                        name: bool(getattr(variant_row, field.key))
                        for name, field in _FORMAT_FIELDS.items()
                        if getattr(variant_row, field.key) is not None
                    },
                    "offers": [],
                })
                if offer_row is not None and store_row is not None:
                    product["offers"].append({
                        "offer_id": str(offer_row.id),
                        "store": store_row.slug,
                        "country": store_row.country,
                        "price": str(offer_row.price),
                        "currency": offer_row.currency,
                        "availability": offer_row.availability,
                        "url": offer_row.url,
                        "captured_at": offer_row.captured_at.isoformat() if offer_row.captured_at else None,
                        "shipping_cost": str(offer_row.shipping_cost) if offer_row.shipping_cost is not None else None,
                    })

            products = list(grouped.values())
            for product in products:
                product["offers"].sort(key=lambda item: (Decimal(item["price"]), item["store"]))
            products.sort(key=lambda item: (
                Decimal(item["offers"][0]["price"]) if item["offers"] else Decimal("Infinity"),
                item["brand"].casefold(),
                item["fragrance"].casefold(),
            ))
            page = products[offset:offset + limit]
            return {
                "query": q,
                "count": len(products),
                "offer_count": sum(len(item["offers"]) for item in products),
                "message": (
                    "Prodotto trovato, ma al momento non ci sono offerte aggiornate."
                    if products and not any(item["offers"] for item in products) else None
                ),
                "suggestions": [],
                "limit": limit,
                "offset": offset,
                "results": page,
            }
    finally:
        if session_factory is None:
            factory.kw["bind"].dispose()
