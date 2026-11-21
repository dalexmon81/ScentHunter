from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.connectors.perfumemarket import PerfumeMarketConnector


class PerfumeMarketConnectorTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_raw_does_not_invent_currency_provenance(self):
        connector = PerfumeMarketConnector(SimpleNamespace())
        parsed = connector.parse_raw({
            "name": "Example Eau de Parfum 100 ml",
            "brand": "Example",
            "url": "https://www.perfumemarket.nl/products/example",
            "price_num": 39.95,
            "currency": "EUR",
            "availability": "in_stock",
            "identity": {"sku": {"value": "SKU-1"}, "gtin": {"value": "1234567890123"}},
            "offer": {"price": 39.95, "currency": "EUR", "availability": "in_stock"},
        })
        self.assertEqual(parsed["price"], "39.95")
        self.assertEqual(parsed["sku"], "SKU-1")
        self.assertEqual(parsed["gtin"], "1234567890123")
        self.assertFalse(parsed["currency_explicit"])
        # The shared structural validator checks URL/price/currency/stock only.
        # Currency provenance is a separate publication gate in connector_ingestion.
        self.assertTrue(connector.validate_offer(parsed).valid)
        self.assertFalse(parsed["currency_explicit"])

    def test_explicit_currency_flag_and_known_stock_pass_validation(self):
        connector = PerfumeMarketConnector(SimpleNamespace())
        parsed = connector.parse_raw({
            "url": "https://www.perfumemarket.nl/products/example",
            "price_num": 39.95,
            "currency": "EUR",
            "currency_explicit": True,
            "availability": "in_stock",
        })
        self.assertTrue(parsed["currency_explicit"])
        self.assertTrue(connector.validate_offer(parsed).valid)

    async def test_discovery_requires_operator_queries(self):
        connector = PerfumeMarketConnector(SimpleNamespace())
        with patch.dict(os.environ, {"SCENTHUNTER_DISCOVERY_QUERIES_PERFUMEMARKET": ""}):
            with self.assertRaises(ValueError):
                await connector.discover_products()

    async def test_discovery_uses_verified_report_and_stable_url_identity(self):
        scraper = SimpleNamespace(search_stream=lambda query: {
            "status": "success", "verified": True, "error": None, "details": {},
            "results": [
                {"url": "https://www.perfumemarket.nl/products/example"},
                {"url": "https://www.perfumemarket.nl/products/example"},
                {"url": "https://www.perfumemarket.nl/collections/all"},
            ],
        })
        connector = PerfumeMarketConnector(scraper)
        with patch.dict(os.environ, {
            "SCENTHUNTER_DISCOVERY_QUERIES_PERFUMEMARKET": "Example Eau de Parfum"
        }):
            products = await connector.discover_products(limit=10)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].external_product_id, "https://www.perfumemarket.nl/products/example")

    async def test_unverified_empty_search_is_not_treated_as_verified_absence(self):
        scraper = SimpleNamespace(search_stream=lambda query: {
            "status": "partial", "verified": False, "error": None,
            "details": {"reason": "no_results_without_authoritative_empty_verification"},
            "results": [],
        })
        connector = PerfumeMarketConnector(scraper)
        with patch.dict(os.environ, {
            "SCENTHUNTER_DISCOVERY_QUERIES_PERFUMEMARKET": "Example"
        }):
            from app.connectors.base import ConnectorUnavailable
            with self.assertRaises(ConnectorUnavailable):
                await connector.discover_products()


if __name__ == "__main__":
    unittest.main()
