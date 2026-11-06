from datetime import datetime, timezone
from decimal import Decimal

from app.connectors.base import OfferRecord, RateLimiter, RetryPolicy, validate_offer


def valid_offer(**changes):
    data = dict(
        store="notino", external_product_id="123", brand="Dior",
        fragrance="Sauvage", concentration="edp", size_ml=100,
        gtin=None, title="Dior Sauvage EDP 100 ml",
        url="https://www.notino.fr/dior-sauvage/p-123/",
        price=Decimal("89.90"), currency="EUR", availability="in_stock",
        captured_at=datetime.now(timezone.utc).isoformat(), source="affiliate_feed",
    )
    data.update(changes)
    return OfferRecord(**data)


def test_standard_payload_uses_camel_case_and_keeps_evidence():
    payload = valid_offer().to_dict()
    assert payload["externalProductId"] == "123"
    assert payload["sizeMl"] == 100
    assert payload["capturedAt"].endswith("+00:00")
    assert payload["price"] == 89.9


def test_offer_validation_rejects_missing_price_url_and_unknown_stock_is_not_in_stock():
    ok, errors = validate_offer(valid_offer(price=None, url="/product", availability="unknown"))
    assert not ok
    assert "missing_price" in errors
    assert "invalid_https_url" in errors
    assert "invalid_currency_code" not in errors
    assert valid_offer(availability="unknown").availability == "unknown"


def test_offer_validation_requires_explicit_timezone_and_valid_currency():
    ok, errors = validate_offer(valid_offer(
        captured_at="2026-11-01T05:40:00", currency=None
    ))
    assert not ok
    assert "captured_at_timezone_required" in errors
    assert "unsupported_or_missing_currency" in errors


def test_rate_limiter_rejects_invalid_rate():
    import pytest
    with pytest.raises(ValueError):
        RateLimiter(0)


def test_retry_policy_retries_transient_failure_then_succeeds():
    import asyncio
    calls = 0
    delays = []
    async def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("temporary")
        return "ok"
    async def fake_sleep(delay):
        delays.append(delay)
    result = asyncio.run(RetryPolicy(max_attempts=2).run(
        operation, sleep=fake_sleep, random_value=lambda: 0
    ))
    assert result == "ok"
    assert calls == 2 and len(delays) == 1
