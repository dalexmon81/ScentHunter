from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.connectors.legacy_scrapers import LegacyScraperConnector


class LegacyScraperConnectorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.scraper = SimpleNamespace(
            search_stream=lambda query: {
                "status": "success",
                "verified": True,
                "results": [
                    {
                        "name": "Example Eau de Parfum 100 ml",
                        "brand": "Example",
                        "url": "https://shop.example/product/123",
                        "price_num": 49.9,
                        "currency": "EUR",
                        "availability": "in_stock",
                        "size_ml": 100,
                        "raw_data": {
                            "jsonld": {
                                "@type": "Product",
                                "offers": {"priceCurrency": "EUR", "price": "49.90"},
                            }
                        },
                    }
                ],
                "error": None,
                "details": {},
            }
        )
        self.connector = LegacyScraperConnector("deloox", self.scraper)

    async def test_discovery_uses_operator_seed_and_stable_product_url(self):
        with patch.dict(os.environ, {
            "SCENTHUNTER_DISCOVERY_QUERIES_DELOOX": "Dior Sauvage;Chanel No 5"
        }):
            products = await self.connector.discover_products(limit=10)
        self.assertEqual(len(products), 2)  # both seed searches are deduplicated by URL
        self.assertEqual(products[0].external_product_id, "https://shop.example/product/123")
        self.assertEqual(products[0].product_url, products[0].external_product_id)

    async def test_discovery_fails_closed_without_operator_seed_queries(self):
        with patch.dict(os.environ, {"SCENTHUNTER_DISCOVERY_QUERIES_DELOOX": ""}):
            with self.assertRaises(ValueError):
                await self.connector.discover_products()

    async def test_parse_raw_preserves_identity_and_explicit_currency_evidence(self):
        raw = {
            "name": "Example Eau de Parfum 100 ml",
            "brand": "Example",
            "url": "https://shop.example/product/123",
            "price_num": 49.9,
            "currency": "EUR",
            "availability": "in_stock",
            "size_ml": 100,
            "raw_data": {
                "jsonld": {"offers": {"priceCurrency": "EUR"}}
            },
        }
        parsed = self.connector.parse_raw(raw)
        self.assertEqual(parsed["price"], "49.9")
        self.assertEqual(parsed["currency"], "EUR")
        self.assertTrue(parsed["currency_explicit"])
        self.assertEqual(parsed["availability"], "in_stock")
        self.assertEqual(parsed["product_url"], raw["url"])
        self.assertEqual(parsed["brand_raw"], "Example")

    async def test_currency_default_is_not_misrepresented_as_explicit(self):
        raw = {
            "name": "Example",
            "url": "https://shop.example/product/123",
            "price_num": 49.9,
            "currency": "EUR",
            "availability": "in_stock",
        }
        parsed = self.connector.parse_raw(raw)
        self.assertFalse(parsed["currency_explicit"])

    async def test_unknown_stock_state_remains_unknown(self):
        parsed = self.connector.parse_raw({
            "name": "Example",
            "url": "https://shop.example/product/123",
            "price_num": 49.9,
            "currency": "EUR",
            "availability": "unknown",
        })
        self.assertIsNone(parsed["availability"])

    async def test_feed_wide_failure_is_classified_for_quarantine(self):
        self.scraper.search_stream = lambda query: {
            "status": "unavailable",
            "verified": False,
            "results": [],
            "error": "HTTP 503",
            "details": {},
        }
        with patch.dict(os.environ, {
            "SCENTHUNTER_DISCOVERY_QUERIES_DELOOX": "Dior Sauvage"
        }):
            from app.connectors.base import ConnectorUnavailable
            with self.assertRaises(ConnectorUnavailable):
                await self.connector.discover_products()


if __name__ == "__main__":
    unittest.main()
