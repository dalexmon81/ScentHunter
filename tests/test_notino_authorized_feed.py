"""Tests for the authenticated Notino CJ/VIV XML feed importer."""
import gzip
import logging
import xml.etree.ElementTree as ET

import pytest

from backend.scrapers.notino import affiliate_feed as feed


SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">
  <channel>
    <title>Notino.fr Google Shopping Export</title>
    <item>
      <g:id>NOTINO-001-100</g:id>
      <g:title>French Avenue Liquid Brun Eau de Parfum 100 ml</g:title>
      <g:brand>French Avenue</g:brand>
      <g:gtin>6291108730001</g:gtin>
      <g:mpn>LB100</g:mpn>
      <g:price>49,90 EUR</g:price>
      <g:availability>in stock</g:availability>
      <g:link>https://www.notino.fr/french-avenue/liquid-brun/?utm_source=feed</g:link>
      <g:image_link>https://cdn.example.test/liquid-brun.jpg</g:image_link>
      <g:size>100 ml</g:size>
    </item>
    <item>
      <g:id>NOTINO-001-150</g:id>
      <g:title>French Avenue Liquid Brun Limited Edition 150 ml</g:title>
      <g:brand>French Avenue</g:brand>
      <g:gtin>6291108730150</g:gtin>
      <g:mpn>LB150LE</g:mpn>
      <g:price>69.90 EUR</g:price>
      <g:availability>in stock</g:availability>
      <g:link>https://notino.fr/french-avenue/liquid-brun-limited-edition/</g:link>
      <g:size>150 ml</g:size>
    </item>
    <item>
      <g:id>NO-PRICE</g:id><g:title>Invalid Eau de Parfum 100 ml</g:title>
      <g:brand>Test</g:brand><g:availability>in stock</g:availability>
      <g:link>https://www.notino.fr/test/invalid/</g:link><g:size>100 ml</g:size>
    </item>
    <item>
      <g:id>FOREIGN</g:id><g:title>Foreign Eau de Parfum 100 ml</g:title>
      <g:brand>Test</g:brand><g:price>20.00 EUR</g:price><g:availability>in stock</g:availability>
      <g:link>https://www.notino.de/test/foreign/</g:link><g:size>100 ml</g:size>
    </item>
  </channel>
</rss>"""


def test_google_shopping_namespace_parses_prices_variant_sizes_stock_and_fr_links():
    offers = feed.parse_feed(SAMPLE)
    assert len(offers) == 2
    by_size = {offer.size_ml: offer for offer in offers}
    assert by_size[100].price == 49.9
    assert by_size[150].price == 69.9
    assert by_size[100].gtin == "6291108730001"
    assert by_size[150].availability == "in_stock"
    assert by_size[150].url == "https://www.notino.fr/french-avenue/liquid-brun-limited-edition/"
    assert by_size[100].url == "https://www.notino.fr/french-avenue/liquid-brun/"
    assert by_size[100].image == "https://cdn.example.test/liquid-brun.jpg"


def test_gzip_and_eu_number_formats():
    assert feed.parse_feed(gzip.compress(SAMPLE))[0].price == 49.9
    price, currency = feed._money("1.299,90 EUR")
    assert float(price) == 1299.9
    assert currency == "EUR"


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        (b"", "notino_feed_empty"),
        (b"<rss><item>", "notino_feed_invalid_xml"),
        (b"<html><body>Access denied</body></html>", "notino_feed_unrecognized_root"),
        (b"<!DOCTYPE rss [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><rss/>",
         "notino_feed_unsafe_xml_declaration"),
        (b"<rss><channel><item><title>No price 100 ml</title></item></channel></rss>",
         "notino_feed_no_valid_priced_fr_offers"),
    ],
)
def test_invalid_feeds_fail_closed(payload, error):
    with pytest.raises(feed.FeedImportError, match=error):
        feed.parse_feed(payload)


def test_item_url_rejects_non_fr_host_credentials_and_non_https():
    assert feed._product_url("https://www.notino.de/brand/item/") is None
    assert feed._product_url("http://www.notino.fr/brand/item/") is None
    assert feed._product_url("https://user:pass@www.notino.fr/brand/item/") is None


def test_no_credentials_fail_without_logging_values(monkeypatch, caplog):
    monkeypatch.delenv("NOTINO_CJ_FEED_URL", raising=False)
    monkeypatch.delenv("NOTINO_CJ_FEED_USERNAME", raising=False)
    monkeypatch.delenv("NOTINO_CJ_FEED_PASSWORD", raising=False)
    with caplog.at_level(logging.INFO, logger="scenthunter.notino_feed"):
        with pytest.raises(feed.FeedImportError, match="notino_feed_credentials_missing"):
            feed.import_configured_feed()
    assert "NOTINO_CJ_FEED_PASSWORD" not in caplog.text
