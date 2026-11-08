"""Regression tests for Notino's authorized CJ/VIV product feed."""
import gzip
import os
import unittest
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Store, StoreAuthorization

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
        # Exercise the credential diagnostic only after a valid, isolated
        # canonical consent record passes the mandatory authorization gate.
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{Path(directory) / 'notino-auth.sqlite'}")
            Base.metadata.create_all(engine)
            factory = sessionmaker(bind=engine, expire_on_commit=False)
            with factory() as session:
                store = Store(
                    name="Notino", slug="notino", domain="notino.fr",
                    country="FR", currency="EUR", status="active",
                )
                session.add(store)
                session.flush()
                session.add(StoreAuthorization(
                    store_id=store.id,
                    status="approved",
                    collection_method="affiliate_feed",
                    scopes=["product_discovery", "offer_data"],
                    authorization_reference="isolated-test-approval",
                    evidence_url="https://affiliate.example.test/approval",
                    approved_by="isolated-test",
                    approved_at=datetime.now(timezone.utc),
                    terms={},
                ))
                session.commit()

            values = {
                "NOTINO_CJ_FEED_URL": "",
                "NOTINO_CJ_FEED_USERNAME": "",
                "NOTINO_CJ_FEED_PASSWORD": "secret-canary-value",
            }
            try:
                with patch("app.db.make_session_factory", return_value=factory):
                    with patch.dict(os.environ, values, clear=False):
                        with self.assertRaisesRegex(feed.FeedImportError, "notino_feed_credentials_missing") as raised:
                            feed.import_configured_feed()
                self.assertNotIn("secret-canary-value", str(raised.exception))
            finally:
                engine.dispose()


    def test_authorized_feed_http_403_and_429_fail_closed_and_close_response(self):
        class FakeResponse:
            def __init__(self, status_code):
                self.status_code = status_code
                self.url = "https://feed.example.test/export.xml"
                self.headers = {"Content-Type": "application/xml"}
                self.closed = False

            def close(self):
                self.closed = True

            def iter_content(self, chunk_size):
                yield b"<rss/>"

        env = {
            "NOTINO_CJ_FEED_URL": "https://feed.example.test/export.xml",
            "NOTINO_CJ_FEED_USERNAME": "publisher",
            "NOTINO_CJ_FEED_PASSWORD": "feed-secret",
        }
        for status_code, expected in (
            (401, "notino_feed_auth_denied"),
            (403, "notino_feed_auth_denied"),
            (429, "notino_feed_http_429"),
        ):
            with self.subTest(status_code=status_code):
                response = FakeResponse(status_code)
                with patch.dict(os.environ, env, clear=False):
                    with patch.object(feed.requests, "get", return_value=response):
                        with self.assertRaisesRegex(feed.FeedImportError, expected) as raised:
                            feed._fetch_feed()
                self.assertTrue(response.closed)
                self.assertNotIn("feed-secret", str(raised.exception))
                self.assertNotIn("publisher", str(raised.exception))
