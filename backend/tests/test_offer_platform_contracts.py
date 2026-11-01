from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from offer_platform.contracts import (
    AdapterRunResult,
    AdapterStatus,
    ProductCandidate,
    RawProductObservation,
    RetailerMarket,
)


NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def observation(**overrides):
    values = {
        "retailer_id": "bplatz",
        "market": "DE",
        "product_url": "https://en.bplatz.de/liquid-brun-100ml",
        "observed_at": NOW,
        "raw_title": "Liquid Brun Eau de Parfum 100 ml",
        "raw_brand": "French Avenue",
        "raw_size": "100 ml",
        "raw_concentration": "Eau de Parfum",
        "price": Decimal("27.50"),
        "currency": "EUR",
        "availability": "in_stock",
        "parser_version": "test-1",
    }
    values.update(overrides)
    return RawProductObservation(**values)


class OfferPlatformContractTests(unittest.TestCase):
    def test_market_requires_explicit_https_market(self):
        market = RetailerMarket("amazon", "DE", "https://www.amazon.de", "EUR", "de-DE")
        self.assertEqual(market.market, "DE")

    def test_candidate_rejects_non_https_or_relative_url(self):
        for url in ("http://shop.example/product", "/product", "javascript:alert(1)"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                ProductCandidate("shop", "DE", url)

    def test_observation_rejects_invalid_price_and_availability(self):
        with self.assertRaises(ValueError):
            observation(price=Decimal("0"))
        with self.assertRaises(ValueError):
            observation(availability="probably_in_stock")

    def test_success_result_requires_observation_and_keeps_market_isolated(self):
        result = AdapterRunResult(
            status=AdapterStatus.SUCCESS,
            retailer_id="bplatz",
            market="DE",
            started_at=NOW,
            finished_at=NOW + timedelta(seconds=1),
            observations=(observation(),),
            candidates_seen=1,
        )
        self.assertEqual(result.observations[0].price, Decimal("27.50"))
        with self.assertRaises(ValueError):
            AdapterRunResult(
                status=AdapterStatus.SUCCESS,
                retailer_id="bplatz",
                market="DE",
                started_at=NOW,
                finished_at=NOW + timedelta(seconds=1),
            )

    def test_failure_status_cannot_smuggle_observations(self):
        with self.assertRaises(ValueError):
            AdapterRunResult(
                status=AdapterStatus.TIMEOUT,
                retailer_id="bplatz",
                market="DE",
                started_at=NOW,
                finished_at=NOW + timedelta(seconds=2),
                observations=(observation(),),
            )

    def test_cross_market_observation_is_rejected(self):
        with self.assertRaises(ValueError):
            AdapterRunResult(
                status=AdapterStatus.SUCCESS,
                retailer_id="bplatz",
                market="FR",
                started_at=NOW,
                finished_at=NOW + timedelta(seconds=1),
                observations=(observation(),),
            )

    def test_out_of_stock_is_a_valid_observation_not_a_failure(self):
        unavailable = observation(price=None, availability="out_of_stock")
        result = AdapterRunResult(
            status=AdapterStatus.OUT_OF_STOCK,
            retailer_id="bplatz",
            market="DE",
            started_at=NOW,
            finished_at=NOW + timedelta(seconds=1),
            observations=(unavailable,),
        )
        self.assertEqual(result.observations[0].availability, "out_of_stock")


if __name__ == "__main__":
    unittest.main()
