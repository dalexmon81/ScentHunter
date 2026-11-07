"""Country-aware shipping quote calculation.

Only fresh verified rates produce a definitive landed total. Estimated or
missing rates are surfaced as such and never rank as confirmed totals.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select

from app.db import make_session_factory
from app.models import Store, StoreShippingRate


def quote_shipping(session, *, store_slug: str, country_code: str,
                   order_subtotal: Decimal | str | float, currency: str = "EUR",
                   postal_code: str | None = None,
                   weight_kg: Decimal | str | float | None = None,
                   now: datetime | None = None) -> dict:
    country = str(country_code or "").strip().upper()
    currency_code = str(currency or "").strip().upper()
    if len(country) != 2 or not country.isalpha():
        raise ValueError("country_code_must_be_iso_3166_1_alpha2")
    if len(currency_code) != 3 or not currency_code.isalpha():
        raise ValueError("currency_must_be_iso_4217")
    subtotal = Decimal(str(order_subtotal))
    if subtotal < 0:
        raise ValueError("order_subtotal_must_be_nonnegative")
    weight = Decimal(str(weight_kg)) if weight_kg is not None else None
    if weight is not None and weight < 0:
        raise ValueError("weight_kg_must_be_nonnegative")

    instant = now or datetime.now(timezone.utc)
    postcode = "".join(str(postal_code or "").upper().split())
    rows = session.scalars(
        select(StoreShippingRate)
        .join(Store, Store.id == StoreShippingRate.store_id)
        .where(Store.slug == store_slug, StoreShippingRate.country_code == country)
    ).all()
    if not rows:
        return {"status": "unknown", "reason": "no_shipping_rule",
                "store": store_slug, "country_code": country, "currency": currency_code}

    applicable = []
    for row in rows:
        prefix = "".join((row.postal_code_prefix or "").upper().split())
        if prefix and (not postcode or not postcode.startswith(prefix)):
            continue
        if row.minimum_order_total is not None and subtotal < row.minimum_order_total:
            continue
        if row.maximum_order_total is not None and subtotal > row.maximum_order_total:
            continue
        if row.minimum_weight_kg is not None and (weight is None or weight < row.minimum_weight_kg):
            continue
        if row.maximum_weight_kg is not None and (weight is None or weight > row.maximum_weight_kg):
            continue
        applicable.append(row)

    if not applicable:
        return {"status": "unknown", "reason": "no_applicable_shipping_rule",
                "store": store_slug, "country_code": country, "currency": currency_code}

    applicable.sort(key=lambda r: (
        len("".join((r.postal_code_prefix or "").split())),
        r.captured_at.isoformat() if r.captured_at else "",
    ), reverse=True)
    rate = applicable[0]
    common = {
        "store": store_slug, "country_code": country, "currency": rate.currency,
        "delivery_min_days": rate.delivery_min_days,
        "delivery_max_days": rate.delivery_max_days,
        "captured_at": rate.captured_at.isoformat() if rate.captured_at else None,
        "valid_until": rate.valid_until.isoformat() if rate.valid_until else None,
        "source_url": rate.source_url, "evidence_reference": rate.evidence_reference,
    }
    if rate.currency != currency_code:
        return {"status": "unknown", "reason": "currency_mismatch", **common}
    if rate.status == "unavailable":
        return {"status": "unavailable",
                "reason": "retailer_does_not_ship_to_destination", **common}
    if rate.status == "verified":
        expiry = rate.valid_until
        if expiry is None:
            return {"status": "stale", "reason": "shipping_rule_expired", **common}
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= instant:
            return {"status": "stale", "reason": "shipping_rule_expired", **common}

    fee = Decimal("0.00") if (
        rate.free_shipping_threshold is not None and subtotal >= rate.free_shipping_threshold
    ) else rate.base_cost
    if fee is None:
        return {"status": "unknown", "reason": "shipping_cost_not_known", **common}
    total = (subtotal + fee).quantize(Decimal("0.01"))
    if rate.status == "verified":
        return {"status": "verified", "shipping_cost": float(fee),
                "order_subtotal": float(subtotal), "total_cost": float(total), **common}
    return {"status": "estimated", "shipping_cost_estimate": float(fee),
            "order_subtotal": float(subtotal), "total_cost_estimate": float(total), **common}


def quote_store_shipping(*, session_factory=None, **kwargs) -> dict:
    owns_factory = session_factory is None
    factory = session_factory or make_session_factory()
    try:
        with factory() as session:
            return quote_shipping(session, **kwargs)
    finally:
        if owns_factory:
            factory.kw["bind"].dispose()
