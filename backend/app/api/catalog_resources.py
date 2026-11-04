"""Catalog resource endpoints for canonical products, brands, stores and offers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, select

from app.db import make_session_factory
from app.models import Brand, Fragrance, Offer, ProductVariant, Store

router = APIRouter(tags=["catalog-resources"])


def _as_utc(value: datetime | None):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _offer_is_expired(offer: Offer, store: Store, now: datetime) -> bool:
    valid_until = _as_utc(offer.valid_until)
    captured_at = _as_utc(offer.captured_at)
    return (
        offer.publication_status == "stale"
        or offer.status != "active"
        or store.status != "active"
        or (valid_until is not None and valid_until <= now)
        or (captured_at is not None and captured_at < now - timedelta(hours=48))
    )


def _offer_payload(offer: Offer, store: Store, *, now: datetime):
    expired = _offer_is_expired(offer, store, now)
    return {
        "id": str(offer.id),
        "store_id": str(store.id),
        "store": store.name,
        "store_slug": store.slug,
        "price": str(offer.price),
        "currency": offer.currency,
        "availability": offer.availability,
        "url": offer.url,
        "captured_at": offer.captured_at.isoformat() if offer.captured_at else None,
        "label": "dato_da_verificare" if expired else None,
        "is_expired": expired,
    }


@router.get("/products/{slug}")
def get_product(slug: str):
    factory = make_session_factory()
    try:
        with factory() as session:
            rows = session.execute(
                select(Brand, Fragrance, ProductVariant)
                .join(Fragrance, Fragrance.brand_id == Brand.id)
                .join(ProductVariant, ProductVariant.fragrance_id == Fragrance.id)
                .where(Fragrance.slug == slug)
                .order_by(ProductVariant.size_ml, ProductVariant.concentration)
            ).all()
            if not rows:
                raise HTTPException(status_code=404, detail="product_not_found")
            brand_ids = {row[0].id for row in rows}
            if len(brand_ids) > 1:
                raise HTTPException(status_code=409, detail="ambiguous_product_slug_use_brand_and_slug")
            brand, fragrance = rows[0][0], rows[0][1]
            variants = [{
                "id": str(variant.id),
                "canonical_key": variant.canonical_key,
                "concentration": variant.concentration,
                "size_ml": variant.size_ml,
                "format": {
                    "tester": variant.is_tester,
                    "refill": variant.is_refill,
                    "gift_set": variant.is_gift_set,
                    "mini": variant.is_mini,
                },
            } for _, _, variant in rows]
            return {
                "brand": {"name": brand.name, "slug": brand.slug},
                "product": {
                    "name": fragrance.name,
                    "slug": fragrance.slug,
                    "family": fragrance.family,
                    "gender": fragrance.gender,
                    "description": fragrance.description,
                    "image_url": fragrance.image_url,
                },
                "variant_selection_required": len(variants) > 1,
                "variants": variants,
            }
    finally:
        factory.kw["bind"].dispose()


@router.get("/products/{slug}/offers")
def get_product_offers(
    slug: str,
    variant_id: UUID | None = None,
    include_expired: bool = True,
):
    factory = make_session_factory()
    try:
        with factory() as session:
            variants = session.execute(
                select(Brand, Fragrance, ProductVariant)
                .join(Fragrance, Fragrance.brand_id == Brand.id)
                .join(ProductVariant, ProductVariant.fragrance_id == Fragrance.id)
                .where(Fragrance.slug == slug)
            ).all()
            if not variants:
                raise HTTPException(status_code=404, detail="product_not_found")
            if variant_id is None and len(variants) > 1:
                raise HTTPException(status_code=409, detail={
                    "code": "variant_selection_required",
                    "variants": [{
                        "id": str(row[2].id),
                        "concentration": row[2].concentration,
                        "size_ml": row[2].size_ml,
                        "is_tester": row[2].is_tester,
                        "is_refill": row[2].is_refill,
                        "is_gift_set": row[2].is_gift_set,
                        "is_mini": row[2].is_mini,
                    } for row in variants],
                })
            selected = [row for row in variants if variant_id is None or row[2].id == variant_id]
            if not selected:
                raise HTTPException(status_code=404, detail="variant_not_found")
            selected_variant = selected[0][2]
            rows = session.execute(
                select(Offer, Store).join(Store, Store.id == Offer.store_id)
                .where(
                    Offer.product_variant_id == selected_variant.id,
                    Offer.status == "active",
                Offer.publication_status.in_(("published", "stale")),
                Store.status == "active",
                    Store.status == "active",
                )
                .order_by(Offer.captured_at.desc(), Offer.price.asc())
            ).all()
            now = datetime.now(timezone.utc)
            offers = [
                _offer_payload(offer, store, now=now)
                for offer, store in rows
                if include_expired or not _offer_is_expired(offer, store, now)
            ]
            return {
                "product_slug": slug,
                "variant_id": str(selected_variant.id),
                "offers": offers,
                "message": "Nessuna offerta disponibile per questa variante." if not offers else None,
            }
    finally:
        factory.kw["bind"].dispose()


@router.get("/brands")
def list_brands(q: str | None = None, limit: int = Query(100, ge=1, le=500)):
    factory = make_session_factory()
    try:
        with factory() as session:
            stmt = select(Brand).order_by(Brand.name).limit(limit)
            if q:
                stmt = stmt.where(Brand.name.ilike(f"%{q.strip()}%"))
            return {"brands": [{"id": str(x.id), "name": x.name, "slug": x.slug} for x in session.scalars(stmt)]}
    finally:
        factory.kw["bind"].dispose()


@router.get("/stores")
def list_stores(active_only: bool = True, limit: int = Query(100, ge=1, le=500)):
    factory = make_session_factory()
    try:
        with factory() as session:
            stmt = select(Store)
            if active_only:
                stmt = stmt.where(Store.status == "active")
            stmt = stmt.order_by(Store.name).limit(limit)
            return {"stores": [{
                "id": str(x.id), "name": x.name, "slug": x.slug,
                "country": x.country, "currency": x.currency,
                "status": x.status, "last_successful_sync_at":
                    x.last_successful_sync_at.isoformat() if x.last_successful_sync_at else None,
            } for x in session.scalars(stmt)]}
    finally:
        factory.kw["bind"].dispose()


@router.get("/offers")
def list_offers(
    storeId: UUID | None = Query(None),
    availability: str | None = None,
    country: str | None = None,
    currency: str | None = None,
    include_expired: bool = False,
    limit: int = Query(100, ge=1, le=500),
):
    factory = make_session_factory()
    try:
        with factory() as session:
            stmt = select(Offer, Store).join(Store, Store.id == Offer.store_id).where(
                Offer.publication_status.in_(("published", "stale")),
            )
            if storeId:
                stmt = stmt.where(Store.id == storeId)
            if availability:
                stmt = stmt.where(Offer.availability == availability.strip().casefold())
            if country:
                stmt = stmt.where(Store.country == country.upper())
            if currency:
                stmt = stmt.where(Offer.currency == currency.upper())
            rows = session.execute(stmt.order_by(Offer.captured_at.desc()).limit(limit)).all()
            now = datetime.now(timezone.utc)
            payload = [
                _offer_payload(offer, store, now=now)
                for offer, store in rows
                if include_expired or not (
                    offer.publication_status == "stale"
                    or store.status != "active"
                    or (offer.valid_until is not None and offer.valid_until <= now)
                    or (offer.captured_at is not None and offer.captured_at < now - timedelta(hours=48))
                )
            ]
            return {"count": len(payload), "offers": payload}
    finally:
        factory.kw["bind"].dispose()
