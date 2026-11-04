"""Explainable offer ranking and price-history analytics.

All scoring is deterministic and uses only persisted offer/store evidence.
No retailer network calls are performed here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from statistics import mean
from typing import Any


def _decimal(value, default=Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value)) if value is not None else default
    except Exception:
        return default


def _utc(value):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def rank_offers(offers: list[dict[str, Any]], *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Return offers sorted by an explainable 0-100 usefulness score.

    Price is compared only inside the same currency. Unknown shipping is not
    treated as free: it receives a transparency deduction.
    """
    now = _utc(now or datetime.now(timezone.utc))
    prepared = []
    minima: dict[str, Decimal] = {}
    for source in offers:
        item = dict(source)
        currency = str(item.get("currency") or "").upper()
        price = _decimal(item.get("price"))
        shipping = _decimal(item.get("shipping_cost")) if item.get("shipping_cost") is not None else None
        landed = price + shipping if shipping is not None else None
        item["_currency"] = currency
        item["_landed"] = landed
        if landed is not None and currency:
            minima[currency] = min(minima.get(currency, landed), landed)
        prepared.append(item)

    ranked = []
    for item in prepared:
        currency = item["_currency"]
        price = _decimal(item.get("price"))
        shipping = _decimal(item.get("shipping_cost")) if item.get("shipping_cost") is not None else None
        landed = item["_landed"]
        best = minima.get(currency)
        # 30 points: relative landed price; never compare different currencies.
        price_score = 15.0 if landed is None or best is None else max(0.0, 30.0 - float((landed - best) / max(best, Decimal("1")) * 30))
        reliability = float(max(Decimal("0"), min(Decimal("1"), _decimal(item.get("store_reliability"), Decimal("0.5")))))
        store_score = reliability * 20.0
        captured = _utc(item.get("captured_at"))
        age_hours = max(0.0, (now - captured).total_seconds() / 3600) if captured else 24 * 30
        freshness_score = 15.0 * (0.5 ** (age_hours / 24.0))
        availability = str(item.get("availability") or "").casefold()
        availability_score = 15.0 if availability in {"in_stock", "available", "instock"} else 6.0 if availability in {"low_stock", "limited"} else 0.0
        confidence = float(max(Decimal("0"), min(Decimal("1"), _decimal(item.get("match_confidence", item.get("confidence")), Decimal("0")))))
        match_score = confidence * 15.0
        shipping_score = 5.0 if shipping is not None else 1.0
        penalties = 0.0
        stale = age_hours > 48 or (item.get("valid_until") is not None and (_utc(item.get("valid_until")) or now) <= now)
        if stale:
            penalties += 20.0
        if str(item.get("store_status") or "active").casefold() == "quarantined":
            penalties += 50.0
        mismatch_rate = max(0.0, min(1.0, float(item.get("mismatch_rate") or 0)))
        penalties += mismatch_rate * 15.0
        score = max(0.0, min(100.0, price_score + store_score + freshness_score + availability_score + match_score + shipping_score - penalties))
        item.update({
            "score": round(score, 2),
            "score_breakdown": {
                "price": round(price_score, 2), "store_reliability": round(store_score, 2),
                "freshness": round(freshness_score, 2), "availability": round(availability_score, 2),
                "match_quality": round(match_score, 2), "shipping_transparency": round(shipping_score, 2),
                "penalties": round(penalties, 2),
            },
            "landed_price": str(landed) if landed is not None else None,
            "verify_price": stale,
            "label": "verifica prezzo" if stale else None,
        })
        item.pop("_currency", None)
        item.pop("_landed", None)
        ranked.append(item)
    return sorted(ranked, key=lambda item: (-item["score"], item.get("store", "")))


def summarize_price_history(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize a single currency series and flag unusually large latest moves."""
    valid = []
    for sample in samples:
        price = _decimal(sample.get("price"), Decimal("-1"))
        captured = _utc(sample.get("captured_at"))
        currency = str(sample.get("currency") or "").upper()
        if price >= 0 and captured and currency:
            valid.append((captured, price, currency))
    if not valid:
        return {"sample_count": 0, "minimum": None, "average": None, "trend": "insufficient_data", "alert": None}
    currencies = {row[2] for row in valid}
    if len(currencies) != 1:
        return {"sample_count": len(valid), "minimum": None, "average": None, "trend": "mixed_currencies", "alert": None}
    valid.sort(key=lambda row: row[0])
    values = [row[1] for row in valid]
    latest = values[-1]
    previous = values[-2] if len(values) > 1 else latest
    change = (latest - previous) / previous if previous else Decimal("0")
    trend = "down" if change <= Decimal("-0.02") else "up" if change >= Decimal("0.02") else "stable"
    alert = None
    if len(values) >= 3:
        baseline = Decimal(str(mean([float(x) for x in values[:-1]])))
        if baseline and abs((latest - baseline) / baseline) >= Decimal("0.20"):
            alert = "unusual_price_drop" if latest < baseline else "unusual_price_increase"
    return {
        "sample_count": len(values), "currency": valid[0][2],
        "minimum": str(min(values)), "average": str(Decimal(str(mean([float(x) for x in values]))).quantize(Decimal("0.01"))),
        "latest": str(latest), "trend": trend, "alert": alert,
    }
