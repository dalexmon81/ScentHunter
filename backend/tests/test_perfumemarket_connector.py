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

    def test_jsonld_offer_currency_provenance_survives_parser_and_adapter(self):
        from scrapers.perfumemarket import scraper

        html = """<h1>Example Eau de Parfum 100 ml</h1>
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Example Eau de Parfum 100 ml",
          "brand": {"@type": "Brand", "name": "Example"},
          "offers": {
            "@type": "Offer",
            "price": "39.95",
            "priceCurrency": "EUR",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>"""

        class Response:
            status_code = 200
            url = "https://www.perfumemarket.nl/products/example"
            text = html

        session = SimpleNamespace(get=lambda *args, **kwargs: Response())
        raw = scraper.extract_product_page(
            session, "https://www.perfumemarket.nl/products/example", "Example"
        )
        self.assertTrue(raw["currency_explicit"])
        self.assertEqual(raw["currency_source"], "jsonld_offer_priceCurrency")
        self.assertEqual(raw["offer"]["currency_source"], "jsonld_offer_priceCurrency")

        parsed = PerfumeMarketConnector(SimpleNamespace()).parse_raw(raw)
        self.assertTrue(parsed["currency_explicit"])
        self.assertEqual(parsed["currency_source"], "jsonld_offer_priceCurrency")
        self.assertTrue(PerfumeMarketConnector(SimpleNamespace()).validate_offer(parsed).valid)

    def test_product_jsonld_currency_without_pricecurrency_remains_unverified(self):
        from scrapers.perfumemarket import scraper

        html = """<h1>Example Eau de Parfum 100 ml</h1>
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Example Eau de Parfum 100 ml",
          "offers": {
            "@type": "Offer",
            "price": "39.95",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>"""

        class Response:
            status_code = 200
            url = "https://www.perfumemarket.nl/products/example"
            text = html

        raw = scraper.extract_product_page(
            SimpleNamespace(get=lambda *args, **kwargs: Response()),
            "https://www.perfumemarket.nl/products/example",
            "Example",
        )
        self.assertEqual(raw["currency"], "EUR")
        self.assertFalse(raw["currency_explicit"])
        self.assertIsNone(raw["currency_source"])

        parsed = PerfumeMarketConnector(SimpleNamespace()).parse_raw(raw)
        self.assertFalse(parsed["currency_explicit"])
        self.assertIsNone(parsed["currency_source"])

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
