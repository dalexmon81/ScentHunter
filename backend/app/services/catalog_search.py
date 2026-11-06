"""Catalog search use cases backed exclusively by persisted canonical identities.

This service never calls retailer connectors or performs live store searches.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select


from app.db import make_session_factory
from app.models import Brand, Fragrance, LegacyProductIdMap, Offer, ProductVariant, Store
from app.services.offer_ranking import rank_offers



def search_catalog(query: str, *, limit: int = 20, session_factory=None):
    """Search canonical brand/fragrance identities and attach persisted offers."""
    term = str(query or "").strip()
    if len(term) < 2 or len(term) > 120:
        raise ValueError("invalid_search_query")
    if not 1 <= limit <= 30:
        raise ValueError("invalid_search_limit")

    owns_factory = session_factory is None
    factory = session_factory or make_session_factory()
    try:
        with factory() as session:
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
                        "image": row.image_url,
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
                            "shipping_cost": (float(row.shipping_cost) if row.shipping_cost is not None else None),
                            "confidence": (float(row.confidence) if row.confidence is not None else None),
                            "reliability_score": (float(row.reliability_score) if row.reliability_score is not None else None),
                            "valid_until": (row.valid_until.isoformat() if row.valid_until else None),
                            "captured_at": (
                                row.captured_at.isoformat()
                                if row.captured_at
                                else None
                            ),
                        }
                    )

            result = []
            for fragrance_id, product in products.items():
                product["variants"] = list(product["variants"].values())
                for variant in product["variants"]:
                    variant["offers"] = rank_offers(variant["offers"])
                legacy_product_id = session.scalar(
                    select(LegacyProductIdMap.legacy_product_id)
                    .where(
                        LegacyProductIdMap.fragrance_id == uuid.UUID(fragrance_id)
                    )
                    .order_by(LegacyProductIdMap.legacy_product_id.asc())
                    .limit(1)
                )
                product["catalog_id"] = legacy_product_id or fragrance_id
                product["canonical_brand"] = product["brand"]
                product["canonical_name"] = product["fragrance"]
                product["identity_only"] = not any(
                    variant["offers"] for variant in product["variants"]
                )
                product["offers"] = []
                for variant in product["variants"]:
                    for offer in variant["offers"]:
                        product["offers"].append(
                            {
                                **offer,
                                "phase2_offer_id": offer["offer_id"],
                                "price_num": offer["price"],
                                "catalog_id": product["catalog_id"],
                                "brand": product["brand"],
                                "canonical_brand": product["brand"],
                                "name": product["fragrance"],
                                "canonical_name": product["fragrance"],
                                "size_ml": variant["size_ml"],
                                "variant": variant["concentration"],
                                "family": product["family"] or "",
                            }
                        )
                result.append(product)
            return {"query": term, "count": len(result), "results": result}
    finally:
        if owns_factory:
            factory.kw["bind"].dispose()



def search_catalog_for_frontend(query: str):
    """Return the legacy progressive-search response contract from PostgreSQL."""
    term = str(query or "").strip()
    if len(term) < 2:
        return {
            "query": term,
            "count": 0,
            "offer_count": 0,
            "results": [],
            "unresolved_offers": [],
            "identity_scope": [],
            "errors": {},
            "stores": {},
            "dedupe_diagnostics": [],
            "completed": True,
            "status": "completed",
        }

    payload = search_catalog(term)
    offers = [
        offer
        for product in payload["results"]
        for offer in product["offers"]
    ]
    stores = {}
    for offer in offers:
        stores.setdefault(
            offer["store"],
            {
                "status": "catalog",
                "verified": True,
                "count": 0,
                "elapsed": 0,
                "details": {"source": "postgresql_published_offers"},
            },
        )["count"] += 1

    return {
        "query": term,
        "count": payload["count"],
        "offer_count": len(offers),
        "results": payload["results"],
        "unresolved_offers": [],
        "identity_scope": [],
        "errors": {},
        "stores": stores,
        "dedupe_diagnostics": [],
        "completed": True,
        "status": "completed",
    }
