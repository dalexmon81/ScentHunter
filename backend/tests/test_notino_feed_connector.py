from __future__ import annotations

import asyncio
import unittest

from app.connectors.notino_feed import NotinoAffiliateFeedConnector


DIOR_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0"><channel>
  <item>
    <g:id>SAUVAGE100</g:id>
    <g:title>Dior Sauvage Eau de Parfum 100 ml</g:title>
    <g:brand>Dior</g:brand>
    <g:gtin>3348901368247</g:gtin>
    <g:price>89.90 EUR</g:price>
    <g:availability>in stock</g:availability>
    <g:link>https://www.notino.fr/dior/sauvage-eau-de-parfum/</g:link>
    <g:size>100 ml</g:size>
  </item>
  <item>
    <g:id>SAUVAGE60</g:id>
    <g:title>Dior Sauvage Eau de Parfum 60 ml</g:title>
    <g:brand>Dior</g:brand>
    <g:price>69.90 EUR</g:price>
    <g:availability>out of stock</g:availability>
    <g:link>https://www.notino.fr/dior/sauvage-eau-de-parfum-60-ml/</g:link>
    <g:size>60 ml</g:size>
  </item>
</channel></rss>"""


class NotinoAffiliateFeedConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovers_dior_products_from_one_structured_feed_snapshot(self) -> None:
        calls = 0

        def load_feed() -> bytes:
            nonlocal calls
            calls += 1
            return DIOR_FEED

        connector = NotinoAffiliateFeedConnector(feed_loader=load_feed)
        products = await connector.discover_products(limit=1)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].external_product_id, "SAUVAGE100")
        self.assertEqual(
            products[0].product_url,
            "https://www.notino.fr/dior/sauvage-eau-de-parfum/",
        )
        second_page = await connector.discover_products(cursor="1", limit=1)
        self.assertEqual(second_page[0].external_product_id, "SAUVAGE60")
        self.assertEqual(calls, 1)

    async def test_fetch_parse_and_validate_dior_edp_100ml(self) -> None:
        connector = NotinoAffiliateFeedConnector(feed_loader=lambda: DIOR_FEED)
        raw = await connector.fetch_product("SAUVAGE100")
        self.assertIsNotNone(raw)
        self.assertIn("<g:id>SAUVAGE100</g:id>", raw["raw_xml"])
        normalized = connector.parse_raw(raw)
        validation = connector.validate_offer(normalized)
        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(normalized["raw_name"], "Dior Sauvage Eau de Parfum 100 ml")
        self.assertEqual(normalized["size_ml"], 100)
        self.assertEqual(normalized["concentration"], "Eau de Parfum")
        self.assertEqual(normalized["currency"], "EUR")

    async def test_out_of_stock_is_valid_but_unknown_stock_is_not(self) -> None:
        connector = NotinoAffiliateFeedConnector(feed_loader=lambda: DIOR_FEED)
        raw = await connector.fetch_product("SAUVAGE60")
        normalized = connector.parse_raw(raw)
        self.assertTrue(connector.validate_offer(normalized).valid)
        normalized["availability"] = "unknown"
        self.assertIn(
            "availability_not_explicit",
            connector.validate_offer(normalized).errors,
        )

    async def test_missing_offer_is_not_fabricated(self) -> None:
        connector = NotinoAffiliateFeedConnector(feed_loader=lambda: DIOR_FEED)
        self.assertIsNone(await connector.fetch_product("NOT-IN-FEED"))
        with self.assertRaises(LookupError):
            await connector.fetch_price_and_stock("NOT-IN-FEED")

    async def test_snapshot_can_be_forced_to_refresh(self) -> None:
        calls = 0

        def load_feed() -> bytes:
            nonlocal calls
            calls += 1
            return DIOR_FEED

        connector = NotinoAffiliateFeedConnector(feed_loader=load_feed)
        await connector.discover_products()
        await connector.refresh_snapshot()
        self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
