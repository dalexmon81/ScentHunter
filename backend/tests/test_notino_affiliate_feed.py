"""Regression tests for Notino's authorized CJ/VIV product feed."""
import gzip
import logging
import os
import unittest
from unittest.mock import patch

from scrapers.notino import affiliate_feed as feed


SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0"><channel>
 <item><g:id>LB100</g:id><g:title>French Avenue Liquid Brun Eau de Parfum 100 ml</g:title>
 <g:brand>French Avenue</g:brand><g:gtin>6291108730001</g:gtin><g:price>49,90 EUR</g:price>
 <g:availability>in stock</g:availability><g:link>https://www.notino.fr/french-avenue/liquid-brun/?utm_source=feed</g:link>
 <g:image_link>https://cdn.example.test/liquid-brun.jpg</g:image_link><g:size>100 ml</g:size></item>
 <item><g:id>LB150LE</g:id><g:title>French Avenue Liquid Brun Limited Edition 150 ml</g:title>
 <g:brand>French Avenue</g:brand><g:gtin>6291108730150</g:gtin><g:price>69.90 EUR</g:price>
 <g:availability>in stock</g:availability><g:link>https://notino.fr/french-avenue/liquid-brun-limited-edition/</g:link>
 <g:size>150 ml</g:size></item>
 <item><g:id>NO-PRICE</g:id><g:title>Invalid Eau de Parfum 100 ml</g:title><g:brand>Test</g:brand>
 <g:availability>in stock</g:availability><g:link>https://www.notino.fr/test/invalid/</g:link><g:size>100 ml</g:size></item>
 <item><g:id>FOREIGN</g:id><g:title>Foreign Eau de Parfum 100 ml</g:title><g:brand>Test</g:brand>
 <g:price>20.00 EUR</g:price><g:availability>in stock</g:availability><g:link>https://www.notino.de/test/foreign/</g:link><g:size>100 ml</g:size></item>
</channel></rss>"""


class NotinoAffiliateFeedTests(unittest.TestCase):
    def test_parses_price_size_gtin_stock_and_french_product_url(self):
        offers = feed.parse_feed(SAMPLE)
        self.assertEqual(len(offers), 2)
        by_size = {offer.size_ml: offer for offer in offers}
        self.assertEqual(by_size[100].price, 49.9)
        self.assertEqual(by_size[150].price, 69.9)
        self.assertEqual(by_size[100].gtin, "6291108730001")
        self.assertEqual(by_size[150].availability, "in_stock")
        self.assertEqual(by_size[100].url, "https://www.notino.fr/french-avenue/liquid-brun/")
        self.assertEqual(by_size[150].url, "https://www.notino.fr/french-avenue/liquid-brun-limited-edition/")
        self.assertEqual(by_size[100].image, "https://cdn.example.test/liquid-brun.jpg")

    def test_gzip_and_european_price_formats(self):
        self.assertEqual(len(feed.parse_feed(gzip.compress(SAMPLE))), 2)
        price, currency = feed._money("1.299,90 EUR")
        self.assertEqual(float(price), 1299.9)
        self.assertEqual(currency, "EUR")

    def test_invalid_feeds_fail_closed(self):
        cases = [
            (b"", "notino_feed_empty"),
            (b"<rss><item>", "notino_feed_invalid_xml"),
            (b"<html><body>Access denied</body></html>", "notino_feed_unrecognized_root"),
            (b"<!DOCTYPE rss [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><rss/>",
             "notino_feed_unsafe_xml_declaration"),
            (b"<rss><channel><item><title>No price 100 ml</title></item></channel></rss>",
             "notino_feed_no_valid_priced_fr_offers"),
        ]
        for payload, error in cases:
            with self.subTest(error=error):
                with self.assertRaisesRegex(feed.FeedImportError, error):
                    feed.parse_feed(payload)

    def test_product_url_requires_https_and_notino_fr(self):
        self.assertIsNone(feed._product_url("https://www.notino.de/brand/item/"))
        self.assertIsNone(feed._product_url("http://www.notino.fr/brand/item/"))
        self.assertIsNone(feed._product_url("https://user:pass@www.notino.fr/brand/item/"))

    def test_missing_credentials_are_reported_without_secrets(self):
        names = ("NOTINO_CJ_FEED_URL", "NOTINO_CJ_FEED_USERNAME", "NOTINO_CJ_FEED_PASSWORD")
        with patch.dict(os.environ, {name: "" for name in names}, clear=False):
            with self.assertLogs("scenthunter.notino_feed", level=logging.INFO) as logs:
                with self.assertRaisesRegex(feed.FeedImportError, "notino_feed_credentials_missing"):
                    feed.import_configured_feed()
            self.assertNotIn("password=", "\n".join(logs.output).lower())
