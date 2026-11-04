from pathlib import Path

from scrapers.notino import affiliate_feed


def test_saved_notino_xml_fixture_parses_product_and_size_variant():
    fixture = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "connectors" / "notino-products.xml"
    offers = affiliate_feed.parse_feed(fixture.read_bytes())
    assert len(offers) == 2
    assert offers[0].brand == "Dior"
    assert offers[0].size_ml == 100
    assert offers[0].availability == "in_stock"
    assert offers[1].size_ml == 60
    assert offers[1].availability == "out_of_stock"


def test_notino_fixture_parser_rejects_missing_price_and_url():
    raw = b'''<rss><channel><item><id>x</id><title>Dior Sauvage EDP 100 ml</title><brand>Dior</brand><availability>in stock</availability><link>https://www.notino.fr/dior/sauvage/p-1/</link></item></channel></rss>'''
    import pytest
    with pytest.raises(affiliate_feed.FeedImportError):
        affiliate_feed.parse_feed(raw)


def test_notino_fixture_parser_rejects_html_schema_change():
    import pytest
    with pytest.raises(affiliate_feed.FeedImportError):
        affiliate_feed.parse_feed(b"<html><body>challenge page</body></html>")
