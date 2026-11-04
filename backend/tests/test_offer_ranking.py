from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.services.offer_ranking import rank_offers, summarize_price_history


def test_rank_uses_reliability_freshness_and_not_price_alone():
    now = datetime.now(timezone.utc)
    offers = [
        {"store": "cheap", "price": "50", "shipping_cost": "0", "currency": "EUR",
         "availability": "in_stock", "captured_at": now, "confidence": "0.99",
         "store_reliability": "0.2", "store_status": "active"},
        {"store": "trusted", "price": "55", "shipping_cost": "0", "currency": "EUR",
         "availability": "in_stock", "captured_at": now, "confidence": "1",
         "store_reliability": "1", "store_status": "active"},
    ]
    ranked = rank_offers(offers, now=now)
    assert ranked[0]["store"] == "trusted"
    assert 0 <= ranked[0]["score"] <= 100
    assert ranked[0]["score_breakdown"]["store_reliability"] == 20


def test_unknown_shipping_is_not_assumed_free_and_stale_is_flagged():
    now = datetime.now(timezone.utc)
    ranked = rank_offers([
        {"store": "known", "price": "40", "shipping_cost": None, "currency": "EUR",
         "availability": "in_stock", "captured_at": now - timedelta(days=4),
         "confidence": "1", "store_reliability": "1"},
    ], now=now)
    assert ranked[0]["verify_price"] is True
    assert ranked[0]["warning"] == "verifica prezzo"
    assert ranked[0]["score_breakdown"]["penalties"] >= 20
    assert ranked[0]["score_breakdown"]["shipping_transparency"] == 1


def test_price_history_min_average_trend_and_anomaly():
    now = datetime.now(timezone.utc)
    samples = [
        {"price": "100", "currency": "EUR", "captured_at": now - timedelta(days=2)},
        {"price": "98", "currency": "EUR", "captured_at": now - timedelta(days=1)},
        {"price": "70", "currency": "EUR", "captured_at": now},
    ]
    result = summarize_price_history(samples)
    assert result["minimum"] == "70"
    assert result["trend"] == "down"
    assert result["alert"] == "unusual_price_drop"
