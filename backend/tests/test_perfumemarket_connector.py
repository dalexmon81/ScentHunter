from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.connectors.legacy_scrapers import (
    LegacyScraperConnector,
    build_legacy_connector,
    connector_key_for_store_slug,
)
from scrapers.perfumemarket import scraper


class PerfumeMarketParserTests(unittest.TestCase):
    def test_product_page_extracts_price_currency_stock_and_identity(self):
        payload = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "Jean Paul Gaultier Le Beau Le Parfum 125ml EDP - Men",
            "brand": {"@type": "Brand", "name": "Jean Paul Gaultier"},
            "sku": "8435415062190",
            "offers": {
                "@type": "Offer",
                "price": "84.99",
                "priceCurrency": "EUR",
                "availability": "https://schema.org/InStock",
            },
        }
        import json

        html = (
            "<html><head><script type='application/ld+json'>"
            + json.dumps(payload)
            + "</script></head><body><h1>Jean Paul Gaultier Le Beau Le Parfum 125ml EDP - Men</h1></body></html>"
        )
        response = SimpleNamespace(
            status_code=200,
            url="https://perfumemarket.eu/products/jpg-le-beau-125ml-edp",
            text=html,
        )
        session = SimpleNamespace(get=lambda *args, **kwargs: response)

        record = scraper.extract_product_page(
            session,
            response.url,
            query="Le Beau Le Parfum",
        )

        self.assertEqual(record["name"], payload["name"])
        self.assertEqual(record["brand"], "Jean Paul Gaultier")
        self.assertEqual(record["price_num"], 84.99)
        self.assertEqual(record["currency"], "EUR")
        self.assertTrue(record["currency_explicit"])
        self.assertEqual(record["availability"], "in_stock")
        self.assertEqual(record["size_ml"], 125)
        self.assertEqual(record["concentration"], "Eau de Parfum")
        self.assertEqual(record["sku"], "8435415062190")
        self.assertEqual(record["raw_data"]["jsonld"]["offers"]["priceCurrency"], "EUR")

    def test_product_page_extracts_gtin_from_visible_upc_label(self):
        import json

        payload = {
            "@type": "Product",
            "name": "Rasasi Hawas London 100ml EDP - Men",
            "brand": {"@type": "Brand", "name": "Rasasi"},
            "offers": {
                "@type": "Offer",
                "price": "30.59",
                "priceCurrency": "EUR",
                "availability": "https://schema.org/InStock",
            },
        }
        html = (
            "<script type='application/ld+json'>"
            + json.dumps(payload)
            + "</script><h1>Rasasi Hawas London 100ml EDP - Men</h1>"
            + "<p>UPC: 614514465059</p>"
        )
        url = "https://perfumemarket.eu/products/rasasi-hawas-london-100ml-edp"
        response = SimpleNamespace(status_code=200, url=url, text=html)
        record = scraper.extract_product_page(
            SimpleNamespace(get=lambda *args, **kwargs: response),
            url,
            query="Rasasi Hawas London",
        )

        self.assertEqual(record["gtin"], "614514465059")
        self.assertEqual(record["identity"]["gtin"]["source"], "product_page_label")

    def test_product_page_does_not_infer_stock_from_generic_page_copy(self):
        payload = {
            "@type": "Product",
            "name": "Example Eau de Parfum 100ml",
            "brand": "Example",
            "offers": {"price": "29.99", "priceCurrency": "EUR"},
        }
        import json

        html = (
            "<script type='application/ld+json'>"
            + json.dumps(payload)
            + "</script><h1>Example Eau de Parfum 100ml</h1>"
            + "<p>Our customer support is available every day.</p>"
        )
        response = SimpleNamespace(
            status_code=200,
            url="https://perfumemarket.eu/products/example-edp-100ml",
            text=html,
        )
        record = scraper.extract_product_page(
            SimpleNamespace(get=lambda *args, **kwargs: response),
            response.url,
            query="Example",
        )
        self.assertEqual(record["availability"], "unknown")
        self.assertIsNone(record["available"])

    def test_product_page_rejects_redirect_to_unrelated_host(self):
        response = SimpleNamespace(
            status_code=200,
            url="https://unrelated.example/products/example",
            text="<h1>Example Eau de Parfum 100ml</h1>",
        )
        record = scraper.extract_product_page(
            SimpleNamespace(get=lambda *args, **kwargs: response),
            "https://perfumemarket.eu/products/example",
            query="Example",
        )
        self.assertIsNone(record)


    def test_plain_parfum_concentration_is_normalized(self):
        self.assertEqual(
            scraper._pm_extract_concentration("Dior Sauvage Parfum 60ml - Men"),
            "Parfum",
        )

    def test_discovery_drops_stale_urls_and_returns_live_product_data(self):
        import json

        product_url = "https://perfumemarket.eu/products/rasasi-hawas-london-100ml-edp"
        payload = {
            "@type": "Product",
            "name": "Rasasi Hawas London 100ml EDP - Men",
            "brand": {"@type": "Brand", "name": "Rasasi"},
            "gtin13": "614514465059",
            "offers": {
                "@type": "Offer",
                "price": "35.99",
                "priceCurrency": "EUR",
                "availability": "https://schema.org/InStock",
            },
        }
        html = (
            "<script type='application/ld+json'>"
            + json.dumps(payload)
            + "</script><h1>Rasasi Hawas London 100ml EDP - Men</h1>"
        )

        class FakeSession:
            def get(self, url, **kwargs):
                if "stale-product" in url:
                    return SimpleNamespace(status_code=404, url=url, text="Not found")
                return SimpleNamespace(status_code=200, url=product_url, text=html)

        candidates = [
            {"name": "Old stale result", "url": "https://perfumemarket.eu/products/stale-product"},
            {"name": "Rasasi Hawas London", "url": product_url},
        ]
        validated = scraper._validate_discovered_products(
            FakeSession(), candidates, "Rasasi Hawas London"
        )

        self.assertEqual(len(validated), 1)
        self.assertEqual(validated[0]["url"], product_url)
        self.assertEqual(validated[0]["price_num"], 35.99)
        self.assertEqual(validated[0]["currency"], "EUR")
        self.assertTrue(validated[0]["currency_explicit"])
        self.assertEqual(validated[0]["availability"], "in_stock")
        self.assertEqual(validated[0]["gtin"], "614514465059")
        self.assertEqual(validated[0]["size_ml"], 100)
        self.assertEqual(validated[0]["concentration"], "Eau de Parfum")


class PerfumeMarketConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_registered_connector_and_store_slug(self):
        self.assertEqual(connector_key_for_store_slug("perfumemarket"), "perfumemarket")
        connector = build_legacy_connector("perfumemarket")
        self.assertEqual(connector.store_key, "perfumemarket")
        self.assertTrue(callable(connector._scraper.search_stream))
        self.assertTrue(callable(connector._scraper.extract_product_page))

    async def test_discovery_and_fetch_preserve_product_url_and_verified_currency(self):
        product_url = "https://perfumemarket.eu/products/jpg-le-beau-125ml-edp"
        raw = {
            "name": "Jean Paul Gaultier Le Beau Le Parfum 125ml EDP - Men",
            "brand": "Jean Paul Gaultier",
            "url": product_url,
            "price_num": 84.99,
            "price": 84.99,
            "currency": "EUR",
            "currency_explicit": True,
            "availability": "in_stock",
            "available": True,
            "size_ml": 125,
            "concentration": "Eau de Parfum",
            "offer": {
                "price": 84.99,
                "currency": "EUR",
                "availability": "in_stock",
            },
            "raw_data": {
                "jsonld": {
                    "@type": "Product",
                    "offers": {
                        "price": "84.99",
                        "priceCurrency": "EUR",
                        "availability": "https://schema.org/InStock",
                    },
                }
            },
        }
        mock_scraper = SimpleNamespace(
            search_stream=lambda query: {
                "status": "success",
                "verified": True,
                "results": [raw],
                "error": None,
                "details": {"count": 1},
            },
            extract_product_page=lambda session, url, query: dict(raw),
        )
        connector = LegacyScraperConnector("perfumemarket", mock_scraper)
        with patch.dict(os.environ, {
            "SCENTHUNTER_DISCOVERY_QUERIES_PERFUMEMARKET": "Jean Paul Gaultier Le Beau"
        }):
            products = await connector.discover_products(limit=10)

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].external_product_id, product_url)
        self.assertEqual(products[0].product_url, product_url)

        fetched = await connector.fetch_product(products[0].external_product_id)
        parsed = connector.parse_raw(fetched)
        self.assertEqual(parsed["product_url"], product_url)
        self.assertEqual(parsed["price"], "84.99")
        self.assertEqual(parsed["currency"], "EUR")
        self.assertTrue(parsed["currency_explicit"])
        self.assertEqual(parsed["availability"], "in_stock")
        self.assertEqual(parsed["size_ml"], 125)
        self.assertEqual(parsed["concentration"], "Eau de Parfum")

    async def test_fetch_rejects_non_retailer_hosts(self):
        connector = LegacyScraperConnector(
            "perfumemarket",
            SimpleNamespace(extract_product_page=lambda session, url, query: {}),
        )
        with self.assertRaisesRegex(ValueError, "canonical HTTPS retailer host"):
            await connector.fetch_product(
                "https://example.com/products/jpg-le-beau-125ml-edp"
            )


if __name__ == "__main__":
    unittest.main()
