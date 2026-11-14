"""Read-only bridge from the isolated Notino Phase 2 DB into public search."""
from __future__ import annotations

import os
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import and_, create_engine, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    Brand, Fragrance, LegacyProductIdMap, NotinoFeedListing, Offer, ProductVariant, Store,
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

    terms = [
        word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        for word in term.split()
    ]
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
                    and_(
                        *(
                            or_(
                                Brand.name.ilike(f"%{word}%", escape="\\"),
                                Fragrance.name.ilike(f"%{word}%", escape="\\"),
                            )
                            for word in terms
                        ),
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
                    "gtin": variant.gtin,
                    "external_id": offer.external_product_id,
                    "store": "notino",
                    "shop": "notino",
                    "price": float(offer.price),
                    "price_num": float(offer.price),
                    "price_stale": (
                        datetime.now(timezone.utc) - (
                            offer.captured_at.replace(tzinfo=timezone.utc)
                            if offer.captured_at.tzinfo is None else offer.captured_at
                        )
                    ).total_seconds() > 24 * 60 * 60,
                    "currency": offer.currency,
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


def search_notino_retailer_listings(query: str, excluded_ids: set[str], limit: int = 100) -> list[dict]:
    """Return feed listings separately, without asserting canonical identity."""
    term = str(query or "").strip()
    if not term:
        return []
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    words = [
        word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        for word in term.split()
    ]
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
                select(NotinoFeedListing)
                .where(
                    NotinoFeedListing.availability.in_(["in stock", "out of stock"]),
                    NotinoFeedListing.currency == "EUR",
                    NotinoFeedListing.price > 0,
                    and_(*(
                        or_(
                            NotinoFeedListing.brand.ilike(f"%{word}%", escape="\\"),
                            NotinoFeedListing.title.ilike(f"%{word}%", escape="\\"),
                        )
                        for word in words
                    )),
                )
                .order_by(NotinoFeedListing.price.asc(), NotinoFeedListing.external_id)
            )
            if excluded_ids:
                stmt = stmt.where(NotinoFeedListing.external_id.not_in(excluded_ids))
            results = []
            for listing in session.scalars(stmt.limit(limit)):
                observed = listing.captured_at
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=timezone.utc)
                source_updated = datetime.fromisoformat(
                    listing.source_last_updated.replace("Z", "+00:00")
                )
                age = (datetime.now(timezone.utc) - min(observed, source_updated)).total_seconds()
                availability = {
                    "in stock": "in_stock",
                    "out of stock": "out_of_stock",
                }[listing.availability]
                results.append({
                    "catalog_id": "notino-feed-" + hashlib.sha256(
                        listing.external_id.encode("utf-8")
                    ).hexdigest()[:24],
                    "external_id": listing.external_id,
                    "gtin": listing.gtin,
                    "brand": listing.brand, "canonical_brand": listing.brand,
                    "name": listing.title, "canonical_name": listing.title,
                    "store": "notino", "shop": "notino",
                    "price": float(listing.price), "price_num": float(listing.price),
                    "price_stale": age > 24 * 60 * 60,
                    "currency": listing.currency, "size_ml": listing.size_ml,
                    "url": listing.affiliate_url, "image": listing.image_url,
                    "available": availability == "in_stock",
                    "in_stock": availability == "in_stock",
                    "availability": availability,
                    "status": "active",
                    "source": "cj_notino_fr_feed",
                    "_match_status": "notino_retailer_only",
                    "_match_policy": "exact_gtin_only",
                    "captured_at": observed.isoformat(),
                })
            return results
    finally:
        engine.dispose()
