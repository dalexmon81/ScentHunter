from pathlib import Path
import asyncio
from decimal import Decimal

from app.connectors.notino import NotinoAffiliateFeedConnector


FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "connectors" / "notino-products.xml"


def test_notino_adapter_maps_xml_to_universal_offer_contract():
    connector = NotinoAffiliateFeedConnector()
    offers = connector.parse_raw(FIXTURE.read_bytes())
    assert len(offers) == 2
    first = offers[0]
    assert first.store == "notino"
    assert first.external_product_id == "nt-123"
    assert first.brand == "Dior"
    assert first.fragrance == "sauvage"
    assert first.concentration == "edp"
    assert first.size_ml == 100
    assert first.price == Decimal("89.90")
    assert first.availability == "in_stock"
    assert first.source == "authorized_affiliate_xml"
    assert connector.validate_offer(first)[0]
    assert offers[1].availability == "out_of_stock"
    assert offers[1].size_ml == 60


def test_notino_discovery_and_refresh_use_injected_feed_without_db_writes():
    payload = FIXTURE.read_bytes()
    connector = NotinoAffiliateFeedConnector(feed_loader=lambda: payload)

    async def exercise():
        discovered = await connector.discover_products()
        assert len(discovered) == 2
        product = await connector.fetch_product("nt-123")
        assert product["externalProductId"] == "nt-123"
        offers = await connector.fetch_offers("nt-124")
        assert len(offers) == 1 and offers[0].availability == "out_of_stock"
        refreshed = await connector.fetch_price_and_stock("nt-123")
        assert refreshed is not None and refreshed.price == Decimal("89.90")

    asyncio.run(exercise())


def test_notino_async_feed_loader_is_supported():
    payload = FIXTURE.read_bytes()
    async def loader():
        return payload
    connector = NotinoAffiliateFeedConnector(feed_loader=loader)
    discovered = asyncio.run(connector.discover_products())
    assert len(discovered) == 2


def test_notino_unknown_stock_is_preserved_not_guessed():
    raw = b'''<rss><channel><item><id>unknown-stock</id><title>Dior Sauvage Eau de Parfum 100 ml</title><brand>Dior</brand><price>89.90 EUR</price><link>https://www.notino.fr/dior/sauvage/p-999/</link><size>100 ml</size></item></channel></rss>'''
    connector = NotinoAffiliateFeedConnector()
    offer = connector.parse_raw(raw)[0]
    assert offer.availability == "unknown"
