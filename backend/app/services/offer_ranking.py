"""Deterministic offer quality ranking for one canonical product variant.

Prices are compared only when both offers have a known delivered-price basis
(product price plus shipping) and the same ISO-like currency code. Unknown
shipping is never treated as zero and cannot win a price comparison.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping


FRESHNESS_WINDOW = timedelta(hours=72)


def _decimal(value, default=Decimal("0")) -> Decimal:
    try:
        parsed = Decimal(str(value))
        return parsed if parsed.is_finite() else default
    except (InvalidOperation, TypeError, ValueError):
        return default


def _datetime(value):
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


def rank_offers(
    offers: Iterable[Mapping],
    *,
    now: datetime | None = None,
) -> list[dict]:
    """Rank offers for one variant, keeping currencies and price bases separate.

    Score (0-100): availability 25, freshness 25, store reliability 20,
    match confidence 20, and comparable delivered price 10. The price
    component is awarded only when shipping is known for that offer and a
    same-currency comparable delivered total exists. Unknown shipping remains
    visible as unknown and receives no price-comparison points.
    """
    reference = _datetime(now or datetime.now(timezone.utc))
    if reference is None:
        raise ValueError("now_must_be_a_datetime")

    rows = [dict(offer) for offer in offers]
    currency_minimum: dict[str, Decimal] = {}
    comparable_totals: list[Decimal | None] = []

    for row in rows:
        currency = str(row.get("currency") or "").strip().upper()
        price = _decimal(row.get("price"), Decimal("-1"))
        shipping = row.get("shipping_cost")
        total = None
        if price > 0 and shipping is not None and len(currency) == 3:
            shipping_value = _decimal(shipping, Decimal("-1"))
            if shipping_value >= 0:
                total = price + shipping_value
                currency_minimum[currency] = min(
                    currency_minimum.get(currency, total), total
                )
        comparable_totals.append(total)

    ranked = []
    for row, total in zip(rows, comparable_totals):
        currency = str(row.get("currency") or "").strip().upper()
        availability = str(row.get("availability") or "").lower()
        availability_score = Decimal("25") if availability == "in_stock" else Decimal("0")

        captured = _datetime(row.get("captured_at"))
        age_seconds = (
            max(0.0, (reference - captured).total_seconds())
            if captured is not None else None
        )
        valid_until = _datetime(row.get("valid_until"))
        expired = valid_until is not None and valid_until < reference
        if age_seconds is None or expired:
            freshness_score = Decimal("0")
        else:
            freshness_score = Decimal("25") * max(
                Decimal("0"),
                Decimal("1") - Decimal(str(age_seconds)) / Decimal(str(FRESHNESS_WINDOW.total_seconds())),
            )

        reliability = min(Decimal("1"), max(Decimal("0"), _decimal(row.get("reliability_score"))))
        confidence = min(Decimal("1"), max(Decimal("0"), _decimal(row.get("confidence"))))
        reliability_score = Decimal("20") * reliability
        match_score = Decimal("20") * confidence

        minimum = currency_minimum.get(currency)
        price_score = (
            Decimal("10") * minimum / total
            if total is not None and minimum is not None and total > 0
            else Decimal("0")
        )
        score = availability_score + freshness_score + reliability_score + match_score + price_score
        shipping_known = row.get("shipping_cost") is not None
        row["ranking"] = {
            "score": round(float(score), 2),
            "currency_scope": currency or None,
            "components": {
                "availability": round(float(availability_score), 2),
                "freshness": round(float(freshness_score), 2),
                "store_reliability": round(float(reliability_score), 2),
                "match_confidence": round(float(match_score), 2),
                "price": round(float(price_score), 2),
            },
            "stale": age_seconds is None or expired or age_seconds > FRESHNESS_WINDOW.total_seconds(),
            "shipping_cost_known": shipping_known,
            "price_basis": "product_plus_shipping" if shipping_known else "product_price_only",
            "price_comparable": total is not None and minimum is not None,
        }
        ranked.append(row)

    # Within each currency, known delivered-price offers are scored by price.
    # Unknown-shipping offers receive no price points and sort after comparable
    # offers when all preceding quality dimensions are equal.
    ranked.sort(
        key=lambda row: (
            str(row.get("currency") or "").strip().upper(),
            -row["ranking"]["score"],
            not row["ranking"]["price_comparable"],
            _decimal(row.get("price"), Decimal("Infinity")),
            str(row.get("store") or ""),
        )
    )
    return ranked
