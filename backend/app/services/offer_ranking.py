"""Deterministic, explainable ranking for already-published catalog offers.

Prices are compared only within the same currency. The ranking deliberately
balances price with freshness, stock, retailer reliability, match confidence,
and shipping transparency so the cheapest stale or uncertain offer cannot
automatically win.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def _decimal(value):
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _bounded_ratio(value):
    number = _decimal(value)
    if number is None:
        return None
    return max(Decimal("0"), min(Decimal("1"), number))


def _utc(value):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _freshness_points(captured_at, now):
    captured = _utc(captured_at)
    if captured is None:
        return 0.0
    age_hours = max(0.0, (now - captured).total_seconds() / 3600)
    if age_hours <= 1:
        return 20.0
    if age_hours <= 6:
        return 18.0
    if age_hours <= 24:
        return 15.0
    if age_hours <= 72:
        return 10.0
    if age_hours <= 168:
        return 5.0
    return 0.0


def rank_offers(offers, *, now=None):
    """Return copied offers sorted by quality score, highest first.

    Score weights (maximum 100): price 35, freshness 20, stock 15,
    retailer reliability 15, match confidence 10, shipping transparency 5.
    Missing reliability/confidence receives a neutral half-score, not a
    fabricated perfect score. Price baselines are currency-specific.
    """
    current = _utc(now) or datetime.now(timezone.utc)
    items = [dict(offer) for offer in offers]
    minimum_by_currency = {}
    for item in items:
        price = _decimal(item.get("price"))
        currency = str(item.get("currency") or "").upper()
        if price is None or price <= 0 or not currency:
            continue
        minimum_by_currency[currency] = min(
            minimum_by_currency.get(currency, price), price
        )

    for item in items:
        price = _decimal(item.get("price"))
        currency = str(item.get("currency") or "").upper()
        minimum = minimum_by_currency.get(currency)
        price_points = (
            float(Decimal("35") * minimum / price)
            if price is not None and price > 0 and minimum is not None
            else 0.0
        )

        captured = _utc(item.get("captured_at"))
        valid_until = _utc(item.get("valid_until"))
        expired = valid_until is not None and valid_until <= current
        freshness_points = 0.0 if expired else _freshness_points(captured, current)

        availability = str(item.get("availability") or "").strip().lower()
        stock_points = 15.0 if availability == "in_stock" and not expired else 0.0

        reliability = _bounded_ratio(item.get("store_reliability"))
        reliability_points = float((reliability if reliability is not None else Decimal("0.5")) * 15)

        confidence = _bounded_ratio(item.get("match_confidence"))
        confidence_points = float((confidence if confidence is not None else Decimal("0.5")) * 10)

        shipping_points = 5.0 if _decimal(item.get("shipping_cost")) is not None else 0.0

        components = {
            "price": round(price_points, 2),
            "freshness": round(freshness_points, 2),
            "availability": round(stock_points, 2),
            "store_reliability": round(reliability_points, 2),
            "match_confidence": round(confidence_points, 2),
            "shipping_transparency": round(shipping_points, 2),
        }
        score = round(sum(components.values()), 2)
        reasons = []
        if price_points >= 34.99:
            reasons.append("competitive_price_in_currency")
        if freshness_points >= 15:
            reasons.append("recently_checked")
        if stock_points:
            reasons.append("in_stock")
        if reliability_points >= 12:
            reasons.append("reliable_store")
        if confidence_points >= 8:
            reasons.append("strong_product_match")
        if shipping_points:
            reasons.append("shipping_cost_disclosed")
        if expired:
            reasons.append("expired_offer")

        item["ranking"] = {
            "score": score,
            "components": components,
            "reasons": reasons,
            "expired": expired,
        }

    items.sort(
        key=lambda item: (
            -item["ranking"]["score"],
            _decimal(item.get("price")) or Decimal("Infinity"),
            -(_utc(item.get("captured_at")) or datetime.min.replace(tzinfo=timezone.utc)).timestamp(),
        )
    )
    for position, item in enumerate(items, start=1):
        item["ranking"]["position"] = position
    return items
