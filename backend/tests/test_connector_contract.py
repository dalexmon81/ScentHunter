"""Unit tests for the provider-neutral retailer connector contract."""

import asyncio
import unittest
from decimal import Decimal

from app.connectors import (
    OfferRecord,
    RateLimiter,
    RetryPolicy,
    capture_raw_page_artifact,
    is_currency_code,
    validate_offer,
    validate_offer_payload,
)


def make_offer(**changes):
    values = {
        "store": "example-store",
        "external_product_id": "sku-123",
        "brand": "Example",
        "fragrance": "Test Fragrance",
        "concentration": "EDP",
        "size_ml": 100,
        "gtin": None,
        "title": "Example Test Fragrance EDP 100 ml",
        "url": "https://shop.example/products/sku-123",
        "price": Decimal("49.90"),
        "currency": "EUR",
        "availability": "in_stock",
        "captured_at": "2026-11-17T12:00:00+00:00",
        "source": "product_feed",
    }
    values.update(changes)
    return OfferRecord(**values)


class ConnectorContractTests(unittest.TestCase):
    def test_valid_offer_passes(self):
        self.assertEqual(validate_offer(make_offer()), (True, ()))

    def test_rejects_non_https_and_credential_urls(self):
        for url in ("http://shop.example/item", "https://user:pass@shop.example/item"):
            with self.subTest(url=url):
                valid, errors = validate_offer(make_offer(url=url))
                self.assertFalse(valid)
                self.assertIn("invalid_https_url", errors)

    def test_rejects_invalid_price_currency_and_timezone(self):
        cases = [
            ({"price": Decimal("0")}, "invalid_price"),
            ({"price": Decimal("NaN")}, "invalid_price"),
            ({"currency": "eur"}, "invalid_currency_code"),
            ({"currency": "EURO"}, "invalid_currency_code"),
            ({"captured_at": "2026-11-17T12:00:00"}, "captured_at_timezone_required"),
        ]
        for changes, expected in cases:
            with self.subTest(changes=changes):
                valid, errors = validate_offer(make_offer(**changes))
                self.assertFalse(valid)
                self.assertIn(expected, errors)

    def test_rejects_missing_identity_and_invalid_availability(self):
        valid, errors = validate_offer(make_offer(brand=" ", availability="maybe"))
        self.assertFalse(valid)
        self.assertIn("missing_brand", errors)
        self.assertIn("invalid_availability", errors)

    def test_payload_contract_uses_camel_case_and_blocks_unknown_stock(self):
        payload = make_offer().to_dict()
        self.assertEqual(payload["externalProductId"], "sku-123")
        self.assertEqual(payload["capturedAt"], "2026-11-17T12:00:00+00:00")
        self.assertEqual(validate_offer_payload(payload), (True, ()))

        payload["availability"] = "unknown"
        valid, errors = validate_offer_payload(payload)
        self.assertFalse(valid)
        self.assertIn("availability_requires_review", errors)

    def test_payload_rejects_non_mapping(self):
        self.assertEqual(validate_offer_payload(None), (False, ("invalid_payload",)))

    def test_currency_code_shape(self):
        self.assertTrue(is_currency_code("EUR"))
        self.assertFalse(is_currency_code("eur"))
        self.assertFalse(is_currency_code("EU"))
        self.assertFalse(is_currency_code(None))

    def test_raw_artifact_preserves_original_bytes(self):
        raw = b"\xff\x00html"
        artifacts = []
        self.assertTrue(capture_raw_page_artifact(
            artifacts, ("https://shop.example/item", raw),
            requested_url="https://fallback.example", store_key="example-store",
        ))
        self.assertEqual(artifacts[0]["data"], raw)
        self.assertEqual(artifacts[0]["source_url"], "https://shop.example/item")

    def test_raw_artifact_rejects_empty_or_unsupported_body(self):
        artifacts = []
        self.assertFalse(capture_raw_page_artifact(
            artifacts, {"html": b""}, requested_url="https://shop.example", store_key="x",
        ))
        self.assertFalse(capture_raw_page_artifact(
            artifacts, {"html": 123}, requested_url="https://shop.example", store_key="x",
        ))
        self.assertEqual(artifacts, [])

    def test_retry_policy_retries_only_transient_errors(self):
        async def scenario():
            attempts = {"count": 0}
            delays = []

            async def operation():
                attempts["count"] += 1
                if attempts["count"] < 3:
                    raise TimeoutError("temporary")
                return "ok"

            async def fake_sleep(delay):
                delays.append(delay)

            result = await RetryPolicy(max_attempts=3, base_delay_seconds=1).run(
                operation, sleep=fake_sleep, random_value=lambda: 0,
            )
            self.assertEqual(result, "ok")
            self.assertEqual(attempts["count"], 3)
            self.assertEqual(delays, [0.5, 1.0])

            async def permanent_error():
                raise ValueError("not transient")

            with self.assertRaises(ValueError):
                await RetryPolicy(max_attempts=5).run(permanent_error)

        asyncio.run(scenario())

    def test_rate_limiter_spaces_calls(self):
        async def scenario():
            now = {"value": 0.0}
            sleeps = []

            def monotonic():
                return now["value"]

            async def fake_sleep(delay):
                sleeps.append(delay)
                now["value"] += delay

            limiter = RateLimiter(requests_per_second=2)
            await limiter.acquire(monotonic=monotonic, sleep=fake_sleep)
            await limiter.acquire(monotonic=monotonic, sleep=fake_sleep)
            self.assertEqual(sleeps, [0.5])

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
