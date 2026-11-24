from __future__ import annotations

import unittest
from decimal import Decimal

from app.offers.contracts import RetailerOffer, decimal_or_none
from app.offers.normalization import normalize_offer, normalize_offers


class OfferNormalizationBoundaryTests(unittest.TestCase):
    def test_legacy_contract_and_normalizer_are_reexports(self):
        from scenthunter_next_engine.models import (
            RetailerOffer as LegacyRetailerOffer,
            decimal_or_none as legacy_decimal_or_none,
        )
        from scenthunter_next_engine.offer_normalizer import (
            normalize_offer as legacy_normalize_offer,
            normalize_offers as legacy_normalize_offers,
        )
        self.assertIs(LegacyRetailerOffer, RetailerOffer)
        self.assertIs(legacy_decimal_or_none, decimal_or_none)
        self.assertIs(legacy_normalize_offer, normalize_offer)
        self.assertIs(legacy_normalize_offers, normalize_offers)

    def test_normalizes_source_record_without_mutating_it(self):
        raw = {
            "title": "Dior Sauvage Eau de Parfum 100 ml",
            "brand": "Dior",
            "price": "89.90",
            "currency": "EUR",
            "availability": "in_stock",
            "url": "https://shop.example/sauvage",
        }
        original = dict(raw)
        result = normalize_offer(raw, retailer="fixture")
        self.assertIsInstance(result, RetailerOffer)
        self.assertEqual(result.raw_name, raw["title"])
        self.assertEqual(result.price, Decimal("89.90"))
        self.assertEqual(result.currency, "EUR")
        self.assertEqual(raw, original)

    def test_batch_normalization_reports_invalid_rows(self):
        offers, rejected = normalize_offers(
            [{"title": "Sauvage"}, {"price": "12.00"}],
            retailer="fixture",
        )
        self.assertEqual(len(offers), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["index"], 1)


if __name__ == "__main__":
    unittest.main()
