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

    async def test_only_belgian_deloox_store_resolves_to_connector(self):
        self.assertEqual(connector_key_for_store_slug("deloox-be"), "deloox")
        for slug in ("deloox-com", "deloox-lu", "deloox-nl", "deloox-es"):
            with self.subTest(slug=slug):
                self.assertIsNone(connector_key_for_store_slug(slug))

    async def test_factory_loads_all_existing_retailer_scraper_modules(self):
        for store_key in ("bplatz", "deloox", "sabina", "easycosmetic", "parfumzentrum", "orioudh"):
            with self.subTest(store_key=store_key):
                connector = build_legacy_connector(store_key)
                self.assertEqual(connector.store_key, store_key)
                self.assertTrue(callable(getattr(connector._scraper, "search_stream", None)))

    async def test_bplatz_discovery_and_refresh_use_product_url_and_explicit_currency(self):
        url = "https://en.bplatz.de/products/liquid-brun-eau-de-parfum-100ml"
        raw = {
            "name": "Liquid Brun Eau de Parfum 100 ml",
            "brand": "French Avenue",
            "url": url,
            "price_num": 24.90,
            "currency": "EUR",
            "currency_explicit": True,
            "availability": "in_stock",
            "size_ml": 100,
            "offer": {"price": 24.90, "currency": "EUR", "currency_explicit": True,
                      "availability": "in_stock"},
            "identity": {"gtin": "54015243419916", "sku": "54015243419916"},
            "attributes": {"size_ml": {"value": 100}, "concentration": {"value": "Eau de Parfum"}},
            "raw_data": {"jsonld": {"offers": {"priceCurrency": "EUR", "price": "24.90"}}},
        }
        scraper = SimpleNamespace(
            search_stream=lambda query: {
                "status": "success", "verified": True, "results": [raw],
                "error": None, "details": {},
            },
            extract_product_page=lambda session, product_url, query: dict(raw),
        )
        connector = LegacyScraperConnector("bplatz", scraper)
        with patch.dict(os.environ, {"SCENTHUNTER_DISCOVERY_QUERIES_BPLATZ": "Liquid Brun"}):
            products = await connector.discover_products(limit=10)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].external_product_id, url)
        observation = await connector.fetch_price_and_stock(products[0].external_product_id)
        self.assertEqual(observation["external_product_id"], url)
        self.assertEqual(observation["currency"], "EUR")
        self.assertTrue(observation["currency_explicit"])
        self.assertEqual(observation["availability"], "in_stock")
        self.assertEqual(observation["product_url"], url)

    async def test_discovery_uses_operator_seed_and_stable_product_url(self):
        with patch.dict(os.environ, {
            "SCENTHUNTER_DISCOVERY_QUERIES_DELOOX": "Dior Sauvage;Chanel No 5"
        }):
            products = await self.connector.discover_products(limit=10)
        self.assertEqual(len(products), 1)  # duplicate product URLs across seed queries collapse
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


    async def test_orioudh_discovery_and_fetch_preserve_each_shopify_variant(self):
        product_url = "https://orioudh.com/products/liquid-brun"
        variants = []
        for variant_id, sku, price, size in (
            (101, "ORI-101", 31.85, 100),
            (202, "ORI-202", 44.90, 150),
        ):
            variants.append({
                "store": "Orioudh",
                "source": {
                    "source_name": f"Liquid Brun French Avenue {size} ml",
                    "source_brand": "French Avenue",
                    "url": product_url,
                },
                "identity": {
                    "sku": {"value": sku, "source": "shopify_variant"},
                    "store_variant_id": {"value": variant_id, "source": "shopify_variant"},
                },
                "attributes": {
                    "size_ml": {"value": size, "source": "product_source"},
                    "concentration": {"value": "Eau de Parfum", "source": "product_source"},
                },
                "offer": {
                    "price": price, "currency": "EUR", "availability": "in_stock",
                },
                "raw_data": {"product": {}, "variant": {"id": variant_id}},
                "name": f"Liquid Brun French Avenue {size} ml",
                "url": product_url,
                "available": True,
            })

        scraper = SimpleNamespace(
            search_stream=lambda query: {
                "status": "success", "verified": True, "results": variants,
                "error": None, "details": {"count": len(variants)},
            },
            extract_product_page=lambda session, url, query: variants,
        )
        connector = LegacyScraperConnector("orioudh", scraper)
        with patch.dict(os.environ, {
            "SCENTHUNTER_DISCOVERY_QUERIES_ORIOUDH": "Liquid Brun"
        }):
            products = await connector.discover_products(limit=10)

        self.assertEqual(len(products), 2)
        self.assertEqual(
            [item.external_product_id for item in products],
            [
                product_url + "?variant=101",
                product_url + "?variant=202",
            ],
        )
        self.assertTrue(all(item.product_url == product_url for item in products))

        first = await connector.fetch_product(products[0].external_product_id)
        self.assertEqual(
            first["identity"]["store_variant_id"]["value"], 101
        )
        self.assertEqual(first["external_product_id"], product_url + "?variant=101")
        self.assertEqual(first["product_url"], product_url)

        observation = await connector.fetch_price_and_stock(products[0].external_product_id)
        self.assertEqual(observation["price"], "31.85")
        self.assertEqual(observation["currency"], "EUR")
        self.assertEqual(observation["availability"], "in_stock")
        # Shopify product JSON alone does not prove the shop currency. Keep the
        # shared ingestion currency-evidence gate closed until separately sourced.
        self.assertFalse(observation["currency_explicit"])

        # Orioudh is not yet enabled as a scheduled production store.
        self.assertIsNone(connector_key_for_store_slug("orioudh"))

    async def test_orioudh_variant_fetch_rejects_non_retailer_hosts(self):
        connector = LegacyScraperConnector(
            "orioudh",
            SimpleNamespace(extract_product_page=lambda session, url, query: []),
        )
        with self.assertRaisesRegex(ValueError, "canonical HTTPS retailer host"):
            await connector.fetch_product("https://example.com/products/liquid-brun?variant=101")


if __name__ == "__main__":
    unittest.main()
