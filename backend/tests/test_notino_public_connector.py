from __future__ import annotations

import unittest
from unittest.mock import patch

from app.connectors.notino_public import NotinoPublicStorefrontConnector
from scrapers.notino import scraper


def test_product_offer_line_excludes_delivery_prices_and_preserves_size():
    page_text = (
        "100 ml 30,00€ En stock | 30,00€ / 100 ml, incl. TVA | Code: FRV00011 "
        "Chronopost 5,99€ Retrait personnel 4,99€"
    )
    offer = scraper._extract_notino_product_offer(page_text)
    assert offer == {
        "price": "30.00",
        "size_ml": 100.0,
        "stock": False,
        "currency_explicit": True,
    }


class NotinoPublicConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_returns_notino_product_urls_without_feed(self):
        connector = NotinoPublicStorefrontConnector()
        candidate = {
            "url": "https://www.notino.fr/dior/sauvage/p-123/",
            "name": "DIOR Sauvage Eau de Parfum",
            "score": 200,
        }
        skincare = {
            "url": "https://www.notino.fr/dior/sauvage-the-toner/p-456/",
            "name": "DIOR Sauvage The Toner lotion tonique visage",
            "score": 190,
        }
        with patch.dict("os.environ", {"SCENTHUNTER_DISCOVERY_QUERIES_NOTINO": "Dior Sauvage Eau de Parfum"}):
            with patch("app.connectors.notino_public.scraper._discover", return_value=([candidate, skincare], {})):
                rows = await connector.discover_products(limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].external_product_id, candidate["url"])
        self.assertEqual(rows[0].product_url, candidate["url"])
        self.assertEqual(connector._candidates[candidate["url"]]["brand"], "DIOR")
        self.assertNotIn(skincare["url"], connector._candidates)

    async def test_fetch_requires_exact_notino_url_and_explicit_currency_evidence(self):
        connector = NotinoPublicStorefrontConnector()
        url = "https://www.notino.fr/dior/sauvage/p-123/"
        candidate = {"url": url, "name": "Dior Sauvage Eau de Parfum", "query": "Dior Sauvage Eau de Parfum"}
        connector._candidates[url] = candidate
        page = {
            "url": url,
            "name": "Dior Sauvage Eau de Parfum",
            "brand": "Dior",
            "price": "89.90 €",
            "availability": "in stock",
            "size_ml": 100,
            "concentration": "Eau de Parfum",
            "currency_explicit": True,
        }
        with patch("app.connectors.notino_public.scraper._reader_product", return_value=page):
            row = await connector.fetch_product(url)
        self.assertEqual(row["source"], "notino_public_storefront")
        self.assertTrue(row["currency_explicit"])
        self.assertEqual(row["availability"], "in_stock")
        self.assertEqual(row["price"], "89.90")
        self.assertTrue(row["captured_at"])

    async def test_fetch_preserves_brand_established_during_discovery(self):
        connector = NotinoPublicStorefrontConnector()
        url = "https://www.notino.fr/dior/sauvage/p-123/"
        connector._candidates[url] = {
            "url": url,
            "name": "DIOR Sauvage Eau de Parfum",
            "brand": "DIOR",
            "query": "Dior Sauvage Eau de Parfum",
        }
        page = {
            "url": url,
            "name": "DIOR Sauvage Eau de Parfum",
            "price": "89.90 €",
            "availability": "in stock",
            "size_ml": 100,
            "concentration": "Eau de Parfum",
            "currency_explicit": True,
        }
        with patch("app.connectors.notino_public.scraper._reader_product", return_value=page):
            row = await connector.fetch_product(url)
        self.assertEqual(row["brand"], "DIOR")

    async def test_fetch_does_not_accept_unknown_stock_or_foreign_destination(self):
        connector = NotinoPublicStorefrontConnector()
        url = "https://www.notino.fr/dior/sauvage/p-123/"
        connector._candidates[url] = {"url": url, "name": "Dior Sauvage", "query": "Dior Sauvage"}
        page = {"url": "https://www.notino.de/dior/sauvage/p-123/", "price": "89.90", "availability": "in stock"}
        with patch("app.connectors.notino_public.scraper._reader_product", return_value=page):
            row = await connector.fetch_product(url)
        self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()
