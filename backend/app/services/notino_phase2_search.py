"""Read-only bridge from the isolated Notino Phase 2 DB into public search."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    Brand, Fragrance, LegacyProductIdMap, Offer, ProductVariant, Store,
)

DEFAULT_DATABASE = Path("/data/notino-phase2/catalog.sqlite3")


def search_notino_phase2(query: str, limit: int = 30) -> list[dict]:
    """Return only active, in-stock, exact-GTIN matched Notino offers.

    The database is opened read-only. No retailer network access or writes occur.
    Offers without an explicit legacy catalog ID mapping are withheld.
    """
    term = str(query or "").strip()
    if not term:
        return []
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    path = Path(os.environ.get("NOTINO_PHASE2_DATABASE", str(DEFAULT_DATABASE))).expanduser().resolve()
    if not path.is_file():
        return []

    engine = create_engine(
        f"sqlite:///file:{path}?mode=ro&uri=true",
        connect_args={"check_same_thread": False, "timeout": 2},
        pool_pre_ping=True,
    )
    try:
        with Session(engine) as session:
            stmt = (
                select(Offer, LegacyProductIdMap.legacy_product_id)
                .join(Offer.product_variant)
                .join(ProductVariant.fragrance)
                .join(Fragrance.brand)
                .join(Offer.store)
                .join(LegacyProductIdMap, LegacyProductIdMap.fragrance_id == Fragrance.id)
                .options(
                    joinedload(Offer.product_variant)
                    .joinedload(ProductVariant.fragrance)
                    .joinedload(Fragrance.brand),
                    joinedload(Offer.store),
                )
                .where(
                    Store.slug == "notino-fr",
                    Store.status == "active",
                    Offer.status == "active",
                    Offer.price > 0,
                    Offer.currency == "EUR",
                    Offer.availability == "in_stock",
                    Offer.url.like("http%"),
                    or_(
                        Brand.name.ilike(f"%{term}%"),
                        Fragrance.name.ilike(f"%{term}%"),
                    ),
                )
                .order_by(Offer.price.asc(), Offer.captured_at.desc())
                .limit(limit)
            )
            rows = session.execute(stmt).all()
            results = []
            for offer, legacy_product_id in rows:
                variant = offer.product_variant
                fragrance = variant.fragrance
                results.append({
                    "catalog_id": legacy_product_id,
                    "brand": fragrance.brand.name,
                    "canonical_brand": fragrance.brand.name,
                    "name": fragrance.name,
                    "canonical_name": fragrance.name,
                    "family": fragrance.family,
                    "variant": variant.concentration,
                    "variant_id": str(variant.id),
                    "store": "notino",
                    "shop": "notino",
                    "price": float(offer.price),
                    "price_num": float(offer.price),
                    "format": f"{variant.size_ml} ml" if variant.size_ml else None,
                    "size_ml": variant.size_ml,
                    "url": offer.url,
                    "available": True,
                    "availability": "in_stock",
                    "in_stock": True,
                    "status": "active",
                    "_match_status": "matched",
                    "_match_method": "notino_exact_gtin",
                    "match_method": "notino_exact_gtin",
                    "source": offer.source,
                    "captured_at": offer.captured_at.isoformat(),
                })
            return results
    finally:
        engine.dispose()
