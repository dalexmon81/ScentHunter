"""Persistence queries for canonical catalog search.

This module owns SQLAlchemy expressions and database row retrieval. It does not
shape API responses or call retailer connectors.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select

from app.models import Brand, Fragrance, LegacyProductIdMap, Offer, ProductVariant, Store


def fetch_catalog_search_rows(session, term: str, limit: int):
    """Fetch canonical fragrance, variant and currently published offer rows."""
    if session.get_bind().dialect.name == "postgresql":
        # Require every query token, while allowing tokens to match
        # either the brand or fragrance name. The matching expressions
        # align with the GIN indexes added in migration 0011.
        tokens = re.findall(r"[^\W_]+", term, flags=re.UNICODE)
        if not tokens:
            raise ValueError("invalid_search_query")
        token_conditions = []
        for token in tokens:
            tsquery = func.plainto_tsquery("simple", token)
            token_conditions.append(
                or_(
                    func.to_tsvector("simple", Brand.name).bool_op("@@")(tsquery),
                    func.to_tsvector("simple", Fragrance.name).bool_op("@@")(tsquery),
                )
            )
        search_condition = and_(*token_conditions)
    else:
        # Keep lightweight SQLite fixtures compatible; production
        # PostgreSQL uses indexed full-text matching above.
        search_condition = or_(
            Fragrance.name.ilike(f"%{term}%"),
            Brand.name.ilike(f"%{term}%"),
        )

    matching_ids = (
        select(Fragrance.id)
        .join(Brand, Brand.id == Fragrance.brand_id)
        .where(search_condition)
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
            Fragrance.image_url.label("image_url"),
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
            Offer.valid_until,
            Offer.shipping_cost,
            Offer.confidence,
            Store.reliability_score,
            Store.slug.label("store_slug"),
        )
        .join(Brand, Brand.id == Fragrance.brand_id)
        .outerjoin(ProductVariant, ProductVariant.fragrance_id == Fragrance.id)
        .outerjoin(
            Offer,
            and_(
                Offer.product_variant_id == ProductVariant.id,
                Offer.status == "active",
                Offer.valid_until.is_not(None),
                Offer.valid_until >= datetime.now(timezone.utc),
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

    return rows


def fetch_legacy_product_id(session, fragrance_id):
    """Return the oldest legacy ID mapped to a canonical fragrance, if any."""
    return session.scalar(
        select(LegacyProductIdMap.legacy_product_id)
        .where(LegacyProductIdMap.fragrance_id == fragrance_id)
        .order_by(LegacyProductIdMap.legacy_product_id.asc())
        .limit(1)
    )
