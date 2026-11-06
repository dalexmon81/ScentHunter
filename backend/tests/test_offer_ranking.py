from datetime import datetime, timedelta, timezone

from app.services.offer_ranking import rank_offers


NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def _offer(store, *, price, shipping_cost, reliability=1, confidence=1):
    return {
        "store": store,
        "currency": "EUR",
        "price": price,
        "shipping_cost": shipping_cost,
        "availability": "in_stock",
        "captured_at": NOW,
        "confidence": confidence,
        "reliability_score": reliability,
    }


def test_ranking_rewards_quality_and_comparable_price_without_hiding_components():
    offers = [
        {
            "store": "reliable",
            "currency": "EUR",
            "price": 100,
            "shipping_cost": 5,
            "availability": "in_stock",
            "captured_at": NOW - timedelta(minutes=15),
            "confidence": 0.99,
            "reliability_score": 0.98,
        },
        {
            "store": "cheap_but_stale",
            "currency": "EUR",
            "price": 80,
            "shipping_cost": 0,
            "availability": "out_of_stock",
            "captured_at": NOW - timedelta(days=5),
            "confidence": 0.60,
            "reliability_score": 0.50,
        },
    ]

    ranked = rank_offers(offers, now=NOW)

    assert ranked[0]["store"] == "reliable"
    assert ranked[0]["ranking"]["score"] > ranked[1]["ranking"]["score"]
    assert ranked[0]["ranking"]["components"]["availability"] == 25
    assert ranked[0]["ranking"]["components"]["freshness"] > 24
    assert ranked[1]["ranking"]["stale"] is True
    assert ranked[0]["ranking"]["shipping_cost_known"] is True


def test_prices_are_compared_only_inside_the_same_currency_group():
    offers = [
        {
            "store": "eur",
            "currency": "EUR",
            "price": 10,
            "shipping_cost": 0,
            "availability": "in_stock",
            "captured_at": NOW,
            "confidence": 1,
            "reliability_score": 1,
        },
        {
            "store": "gbp",
            "currency": "GBP",
            "price": 1,
            "shipping_cost": 0,
            "availability": "in_stock",
            "captured_at": NOW,
            "confidence": 1,
            "reliability_score": 1,
        },
        {
            "store": "eur_expensive",
            "currency": "EUR",
            "price": 20,
            "shipping_cost": 0,
            "availability": "in_stock",
            "captured_at": NOW,
            "confidence": 1,
            "reliability_score": 1,
        },
    ]

    ranked = rank_offers(offers, now=NOW)
    by_store = {row["store"]: row for row in ranked}

    assert by_store["eur"]["ranking"]["components"]["price"] == 10
    assert by_store["eur_expensive"]["ranking"]["components"]["price"] == 5
    assert by_store["gbp"]["ranking"]["components"]["price"] == 10
    assert by_store["eur"]["ranking"]["currency_scope"] == "EUR"
    assert by_store["gbp"]["ranking"]["currency_scope"] == "GBP"


def test_missing_shipping_is_not_silently_counted_as_zero_shipping():
    ranked = rank_offers(
        [_offer("unknown_shipping", price=40, shipping_cost=None)],
        now=NOW,
    )

    assert ranked[0]["ranking"]["shipping_cost_known"] is False
    assert ranked[0]["ranking"]["price_basis"] == "product_price_only"
    assert ranked[0]["ranking"]["price_comparable"] is False
    assert ranked[0]["ranking"]["components"]["price"] == 0


def test_unknown_shipping_does_not_set_the_delivered_price_benchmark():
    ranked = rank_offers(
        [
            _offer("unknown_shipping", price=1, shipping_cost=None),
            _offer("known_shipping", price=50, shipping_cost=5),
        ],
        now=NOW,
    )
    by_store = {row["store"]: row for row in ranked}

    assert by_store["known_shipping"]["ranking"]["components"]["price"] == 10
    assert by_store["known_shipping"]["ranking"]["price_comparable"] is True
    assert by_store["unknown_shipping"]["ranking"]["components"]["price"] == 0
    assert by_store["unknown_shipping"]["ranking"]["price_comparable"] is False


def test_unknown_shipping_does_not_beat_comparable_offer_on_equal_quality():
    ranked = rank_offers(
        [
            _offer("unknown_shipping", price=40, shipping_cost=None),
            _offer("known_shipping", price=45, shipping_cost=5),
        ],
        now=NOW,
    )

    assert ranked[0]["store"] == "known_shipping"
    assert ranked[1]["store"] == "unknown_shipping"


def test_expired_offer_has_no_freshness_points():
    ranked = rank_offers(
        [{
            "store": "expired",
            "currency": "EUR",
            "price": 40,
            "shipping_cost": 0,
            "availability": "in_stock",
            "captured_at": NOW,
            "valid_until": NOW - timedelta(seconds=1),
            "confidence": 1,
            "reliability_score": 1,
        }],
        now=NOW,
    )

    assert ranked[0]["ranking"]["components"]["freshness"] == 0
    assert ranked[0]["ranking"]["stale"] is True
