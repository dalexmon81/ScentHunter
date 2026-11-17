"""Read-only search of canonical variants and previously promoted offers."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.models import Brand, Fragrance, IngestionRaw, MatchAudit, Offer, ProductVariant, Store


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


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


def search_catalog(session: Session, query: str, *, now: datetime | None = None) -> dict:
    """Search the database only; never contact a retailer or mutate catalog data."""
    now = _utc(now or datetime.now(timezone.utc))
    tokens = re.findall(r"[^\W\d_]+|\d+", query.casefold(), flags=re.UNICODE)
    if not tokens or all(token == "ml" for token in tokens):
        return {"query": query, "count": 0, "offer_count": 0, "results": [], "status": "completed", "completed": True}

    text_fields = (Brand.name, Fragrance.name, ProductVariant.concentration)
    statement = select(ProductVariant, Fragrance, Brand).join(
        Fragrance, ProductVariant.fragrance_id == Fragrance.id
    ).join(Brand, Fragrance.brand_id == Brand.id)
    for token in tokens:
        if token == "ml":
            continue
        if token.isdecimal():
            if len(token) > 5 or int(token) > 10000:
                return {"query": query, "count": 0, "offer_count": 0, "results": [], "status": "completed", "completed": True}
            statement = statement.where(ProductVariant.size_ml == int(token))
        elif token in {"edp", "edt"}:
            concentration = "eau de parfum" if token == "edp" else "eau de toilette"
            statement = statement.where(or_(
                func.lower(ProductVariant.concentration).contains(concentration, autoescape=True),
                func.lower(ProductVariant.concentration) == token,
            ))
        elif token in {"tester", "refill"}:
            statement = statement.where(
                (ProductVariant.is_tester if token == "tester" else ProductVariant.is_refill).is_(True)
            )
        else:
            statement = statement.where(or_(*(
                func.lower(field).contains(token, autoescape=True) for field in text_fields
            )))
    rows = session.execute(statement.order_by(Brand.name, Fragrance.name, ProductVariant.size_ml, ProductVariant.id).limit(50)).all()
    variant_ids = [variant.id for variant, _, _ in rows]
    sizes = {variant.id: variant.size_ml for variant, _, _ in rows}
    offers_by_variant: dict = {}
    if variant_ids:
        audit_exists = exists(select(MatchAudit.id).where(
            MatchAudit.offer_id == Offer.id,
            MatchAudit.product_variant_id == Offer.product_variant_id,
        ))
        offer_rows = session.execute(
            select(Offer, Store, IngestionRaw).join(Store, Offer.store_id == Store.id)
            .join(IngestionRaw, Offer.ingestion_raw_id == IngestionRaw.id)
            .where(
                Offer.product_variant_id.in_(variant_ids),
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
            ).order_by(Offer.price, Offer.id)
        ).all()
        for offer, store, raw in offer_rows:
            if raw.raw_payload.get("currency_explicit") is not True or not _offer_url_valid(offer.url, store.domain):
                continue
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
            f"{variant.size_ml} ml" if variant.size_ml else None,
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
