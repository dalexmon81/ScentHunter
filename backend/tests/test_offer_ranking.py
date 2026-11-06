from datetime import datetime, timedelta, timezone

from app.services.offer_ranking import rank_offers


def test_fresh_reliable_in_stock_offer_can_outrank_cheaper_stale_offer():
    now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
    offers = [
        {
            "offer_id": "cheap-stale",
            "price": 40.0,
            "currency": "EUR",
            "availability": "out_of_stock",
            "captured_at": now - timedelta(days=14),
            "store_reliability": 0.1,
            "match_confidence": 0.3,
            "shipping_cost": None,
        },
        {
            "offer_id": "reliable-fresh",
            "price": 80.0,
            "currency": "EUR",
            "availability": "in_stock",
            "captured_at": now - timedelta(minutes=20),
            "store_reliability": 1.0,
            "match_confidence": 1.0,
            "shipping_cost": 0.0,
        },
    ]

    ranked = rank_offers(offers, now=now)

    assert [row["offer_id"] for row in ranked] == [
        "reliable-fresh",
        "cheap-stale",
    ]
    assert ranked[0]["ranking"]["score"] > ranked[1]["ranking"]["score"]
    assert "in_stock" in ranked[0]["ranking"]["reasons"]
    assert "recently_checked" in ranked[0]["ranking"]["reasons"]


def test_price_is_compared_only_within_the_same_currency():
    now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
    ranked = rank_offers(
        [
            {
                "offer_id": "eur",
                "price": 50,
                "currency": "EUR",
                "availability": "in_stock",
                "captured_at": now,
            },
            {
                "offer_id": "usd",
                "price": 10,
                "currency": "USD",
                "availability": "in_stock",
                "captured_at": now,
            },
        ],
        now=now,
    )

    by_id = {row["offer_id"]: row for row in ranked}
    assert by_id["eur"]["ranking"]["components"]["price"] == 35.0
    assert by_id["usd"]["ranking"]["components"]["price"] == 35.0


def test_expired_offer_is_marked_and_loses_stock_and_freshness_points():
    now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
    ranked = rank_offers(
        [
            {
                "offer_id": "expired",
                "price": 10,
                "currency": "EUR",
                "availability": "in_stock",
                "captured_at": now,
                "valid_until": now - timedelta(minutes=1),
            }
        ],
        now=now,
    )

    assert ranked[0]["ranking"]["expired"] is True
    assert ranked[0]["ranking"]["components"]["freshness"] == 0.0
    assert ranked[0]["ranking"]["components"]["availability"] == 0.0
    assert "expired_offer" in ranked[0]["ranking"]["reasons"]


def test_missing_optional_signals_use_neutral_scores_not_perfect_scores():
    now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
    ranked = rank_offers(
        [
            {
                "offer_id": "unknown-metadata",
                "price": 30,
                "currency": "EUR",
                "availability": "in_stock",
                "captured_at": now,
            }
        ],
        now=now,
    )

    components = ranked[0]["ranking"]["components"]
    assert components["store_reliability"] == 7.5
    assert components["match_confidence"] == 5.0
    assert components["shipping_transparency"] == 0.0
