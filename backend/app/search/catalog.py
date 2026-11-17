"""Read-only search of canonical variants and previously promoted offers."""
from __future__ import annotations

import re
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.models import Brand, Fragrance, IngestionRaw, MatchAudit, Offer, ProductVariant, Store


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _format_size_ml(value) -> str | None:
    if value is None:
        return None
    amount = Decimal(str(value))
    if amount == amount.to_integral_value():
        return str(int(amount))
    return format(amount.normalize(), "f")


def _offer_url_valid(url: str, domain: str | None) -> bool:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        allowed = (domain or "").lower().rstrip(".")
        return (
            parsed.scheme in {"http", "https"} and bool(allowed)
            and (host == allowed or host.endswith("." + allowed))
            and parsed.username is None and parsed.password is None
            and parsed.port in (None, 80, 443)
        )
    except ValueError:
        return False


def _eligible_offer_rows(session: Session, now: datetime, variant_ids: list | None = None):
    audit_exists = exists(select(MatchAudit.id).where(
        MatchAudit.offer_id == Offer.id,
        MatchAudit.product_variant_id == Offer.product_variant_id,
    ))
    statement = (
        select(Offer, Store, IngestionRaw)
        .join(Store, Offer.store_id == Store.id)
        .join(IngestionRaw, Offer.ingestion_raw_id == IngestionRaw.id)
        .where(
            Offer.status == "active",
            Store.status == "active",
            IngestionRaw.status == "promoted",
            IngestionRaw.product_variant_id == Offer.product_variant_id,
            IngestionRaw.store_id == Offer.store_id,
            Offer.availability == "in_stock",
            Offer.price > 0,
            Offer.currency == "EUR",
            Offer.captured_at >= now - timedelta(hours=24),
            Offer.captured_at <= now,
            or_(Offer.valid_until.is_(None), Offer.valid_until > now),
            audit_exists,
        )
    )
    if variant_ids is not None:
        if not variant_ids:
            return []
        statement = statement.where(Offer.product_variant_id.in_(variant_ids))
    rows = session.execute(statement.order_by(Offer.price, Offer.id)).all()
    return [
        (offer, store, raw) for offer, store, raw in rows
        if raw.raw_payload.get("currency_explicit") is True
        and _offer_url_valid(offer.url, store.domain)
    ]


def search_catalog(session: Session, query: str, *, now: datetime | None = None) -> dict:
    """Search the database only; never contact a retailer or mutate catalog data."""
    now = _utc(now or datetime.now(timezone.utc))
    tokens = re.findall(r"[^\W\d_]+|\d+(?:[.,]\d+)?", query.casefold(), flags=re.UNICODE)
    if not tokens or all(token == "ml" for token in tokens):
        return {"query": query, "count": 0, "offer_count": 0, "results": [], "status": "completed", "completed": True}

    text_fields = (Brand.name, Fragrance.name, ProductVariant.concentration)
    statement = select(ProductVariant, Fragrance, Brand).join(
        Fragrance, ProductVariant.fragrance_id == Fragrance.id
    ).join(Brand, Fragrance.brand_id == Brand.id)
    for token in tokens:
        if token == "ml":
            continue
        if re.fullmatch(r"\d+(?:[.,]\d+)?", token):
            amount = Decimal(token.replace(",", "."))
            if amount <= 0 or amount > Decimal("10000"):
                return {"query": query, "count": 0, "offer_count": 0, "results": [], "status": "completed", "completed": True}
            statement = statement.where(ProductVariant.size_ml == amount)
        elif token in {"edp", "edt"}:
            concentration = "eau de parfum" if token == "edp" else "eau de toilette"
            statement = statement.where(or_(
                func.lower(ProductVariant.concentration).contains(concentration, autoescape=True),
                func.lower(ProductVariant.concentration) == token,
            ))
        elif token in {"tester", "refill", "gift", "set"}:
            flag = (
                ProductVariant.is_tester if token == "tester" else
                ProductVariant.is_refill if token == "refill" else
                ProductVariant.is_gift_set
            )
            statement = statement.where(flag.is_(True))
        else:
            statement = statement.where(or_(*(
                func.lower(field).contains(token, autoescape=True) for field in text_fields
            )))
    rows = session.execute(statement.order_by(Brand.name, Fragrance.name, ProductVariant.size_ml, ProductVariant.id).limit(50)).all()
    variant_ids = [variant.id for variant, _, _ in rows]
    sizes = {variant.id: variant.size_ml for variant, _, _ in rows}
    offers_by_variant: dict = {}
    for offer, store, _raw in _eligible_offer_rows(session, now, variant_ids):
        offers_by_variant.setdefault(offer.product_variant_id, []).append({
            "store": store.name,
            "url": offer.url,
            "price": str(offer.price),
            "currency": offer.currency,
            "availability": offer.availability,
            "size_ml": sizes[offer.product_variant_id],
            "captured_at": _utc(offer.captured_at).isoformat(),
            "shipping_cost": str(offer.shipping_cost) if offer.shipping_cost is not None else None,
        })

    results = []
    for variant, fragrance, brand in rows:
        label = " ".join(filter(None, (
            fragrance.name, variant.concentration,
            f"{_format_size_ml(variant.size_ml)} ml" if variant.size_ml is not None else None,
            "Tester" if variant.is_tester else None,
            "Refill" if variant.is_refill else None,
            "Gift set" if variant.is_gift_set else None,
        )))
        results.append({
            "catalog_id": str(variant.id),
            "brand": brand.name,
            "name": label,
            "image": fragrance.image_url,
            "offers": offers_by_variant.get(variant.id, []),
        })
    return {
        "query": query, "count": len(results),
        "offer_count": sum(len(result["offers"]) for result in results),
        "results": results, "status": "completed", "completed": True,
    }


def catalog_status(session: Session, *, now: datetime | None = None) -> dict:
    """Return read-only operational counts using the exact public-offer gate."""
    now = _utc(now or datetime.now(timezone.utc))
    stores = session.scalars(select(Store).order_by(Store.slug)).all()
    active_stores = [store for store in stores if store.status == "active"]
    eligible = _eligible_offer_rows(session, now)
    offers_by_store = {store.slug: 0 for store in active_stores}
    latest_by_store = {}
    for offer, store, _raw in eligible:
        offers_by_store[store.slug] = offers_by_store.get(store.slug, 0) + 1
        captured_at = _utc(offer.captured_at)
        previous = latest_by_store.get(store.slug)
        if previous is None or captured_at > previous:
            latest_by_store[store.slug] = captured_at
    active_offer_count = session.scalar(
        select(func.count()).select_from(Offer).where(Offer.status == "active")
    ) or 0
    unresolved_count = session.scalar(
        select(func.count()).select_from(IngestionRaw).where(
            IngestionRaw.status.in_(("pending", "unmatched"))
        )
    ) or 0
    return {
        "status": "ready",
        "canonical_products": session.scalar(select(func.count()).select_from(Fragrance)) or 0,
        "canonical_variants": session.scalar(select(func.count()).select_from(ProductVariant)) or 0,
        "active_stores": len(active_stores),
        "published_offers": len(eligible),
        "offers_by_store": offers_by_store,
        "latest_offer_update_by_store": {
            slug: value.isoformat() for slug, value in latest_by_store.items()
        },
        "active_offers_not_currently_publishable": max(0, active_offer_count - len(eligible)),
        "unresolved_match_reviews": unresolved_count,
        "freshness_window_hours": 24,
    }
