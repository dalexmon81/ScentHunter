from pathlib import Path
import asyncio

from app.connectors.easycosmetic import EasycosmeticConnector

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "connectors" / "easycosmetic-product.html"
URL = "https://www.easycosmetic.de/p/dior-sauvage-edp-100ml"


def test_easycosmetic_saved_product_fixture_maps_to_universal_offer():
    connector = EasycosmeticConnector()
    records = connector.parse_raw((URL, FIXTURE.read_text(encoding="utf-8")))
    assert len(records) == 1
    offer = records[0]
    assert offer.store == "easycosmetic"
    assert offer.brand == "Dior"
    assert offer.fragrance == "sauvage"
    assert offer.concentration == "edp"
    assert offer.size_ml == 100
    assert offer.price is not None and str(offer.price) == "84.95"
    assert offer.currency == "EUR"
    assert offer.availability == "in_stock"
    assert connector.validate_offer(offer)[0]


def test_easycosmetic_unknown_stock_is_not_invented():
    connector = EasycosmeticConnector()
    row = {"name": "Dior Sauvage Eau de Parfum 100 ml", "brand": "Dior",
           "url": URL, "price_num": 84.95, "currency": "EUR",
           "availability": "", "available": None, "size_ml": 100}
    offer = connector.parse_raw(row)[0]
    assert offer.availability == "unknown"


def test_easycosmetic_discovery_uses_injected_search():
    row = {"name": "Dior Sauvage Eau de Parfum 100 ml", "brand": "Dior",
           "url": URL, "price_num": 84.95, "currency": "EUR",
           "availability": "In stock", "available": True, "size_ml": 100}
    connector = EasycosmeticConnector(["Dior Sauvage"], search_func=lambda query: [row])
    async def run():
        found = await connector.discover_products()
        assert len(found) == 1
        offers = await connector.fetch_offers(URL)
        assert len(offers) == 1
    asyncio.run(run())
