from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.connectors.bplatz import BplatzConnector


class BplatzConnectorTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_raw_preserves_currency_provenance_and_unknown_stock(self):
        connector = BplatzConnector(SimpleNamespace())
        parsed = connector.parse_raw({
            "name": "French Avenue Liquid Brun Eau de Parfum 100 ml",
            "source": {
                "source_name": "French Avenue Liquid Brun Eau de Parfum 100 ml",
                "source_brand": "French Avenue",
                "url": "https://en.bplatz.de/products/liquid-brun",
            },
            "identity": {"gtin": "54015243419916", "sku": "LB100"},
            "attributes": {
                "size_ml": {"value": 100, "source": "product_page"},
                "concentration": {"value": "Eau de Parfum", "source": "product_title"},
            },
            "offer": {
                "price": 27.5, "currency": "EUR",
                "currency_explicit": False, "availability": "unknown",
            },
        })
        self.assertEqual(parsed["gtin"], "54015243419916")
        self.assertEqual(parsed["sku"], "LB100")
        self.assertEqual(parsed["size_ml"], 100)
        self.assertEqual(parsed["price"], "27.5")
        self.assertEqual(parsed["currency"], "EUR")
        self.assertFalse(parsed["currency_explicit"])
        self.assertEqual(parsed["availability"], "unknown")
        self.assertFalse(connector.validate_offer(parsed).valid)

    def test_explicit_stock_and_currency_pass_common_gate(self):
        connector = BplatzConnector(SimpleNamespace())
        parsed = connector.parse_raw({
            "source": {"url": "https://en.bplatz.de/products/liquid-brun"},
            "offer": {
                "price": 27.5, "currency": "EUR",
                "currency_explicit": True, "availability": "in_stock",
            },
        })
        self.assertTrue(connector.validate_offer(parsed).valid)

    async def test_discovery_requires_operator_queries(self):
        connector = BplatzConnector(SimpleNamespace())
        with patch.dict(os.environ, {"SCENTHUNTER_DISCOVERY_QUERIES_BPLATZ": ""}):
            with self.assertRaises(ValueError):
                await connector.discover_products()

    async def test_discovery_uses_fixture_scraper_and_stable_url_identity(self):
        scraper = SimpleNamespace(discover=lambda session, query: (
            ["https://en.bplatz.de/products/liquid-brun"], [], True
        ))
        connector = BplatzConnector(scraper)
        with patch.dict(os.environ, {
            "SCENTHUNTER_DISCOVERY_QUERIES_BPLATZ": "French Avenue Liquid Brun"
        }):
            products = await connector.discover_products(limit=10)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].external_product_id, products[0].product_url)
        self.assertEqual(products[0].external_product_id, "https://en.bplatz.de/products/liquid-brun")


if __name__ == "__main__":
    unittest.main()
