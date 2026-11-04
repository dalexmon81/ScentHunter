from pathlib import Path
import asyncio
import pytest

from app.connectors.parfumzentrum import ParfumzentrumConnector

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "connectors" / "parfumzentrum-product.html"
URL = "https://www.parfum-zentrum.de/afnan-9-pm-eau-de-parfum-100-ml_z904294/"


def test_parfumzentrum_saved_jsonld_fixture_maps_to_universal_offer():
    connector = ParfumzentrumConnector()
    records = connector.parse_raw((URL, FIXTURE.read_text(encoding="utf-8")))
    assert len(records) == 1
    offer = records[0]
    assert offer.store == "parfumzentrum"
    assert offer.external_product_id == "pz-9pm-100"
    assert offer.brand == "Afnan"
    assert offer.fragrance == "9 pm"
    assert offer.concentration == "edp"
    assert offer.size_ml == 100
    assert str(offer.price) == "28.95"
    assert offer.currency == "EUR"
    assert offer.availability == "in_stock"
    assert connector.validate_offer(offer)[0]


def test_parfumzentrum_unknown_stock_is_not_invented():
    row = {"name": "Afnan 9 PM Eau de Parfum 100 ml", "brand": "Afnan",
           "url": URL, "price_num": 28.95, "availability": "unknown",
           "available": None, "size_ml": 100, "sku": "pz-9pm-100"}
    assert ParfumzentrumConnector().parse_raw(row)[0].availability == "unknown"


def test_parfumzentrum_discovery_uses_injected_search():
    row = {"name": "Afnan 9 PM Eau de Parfum 100 ml", "brand": "Afnan",
           "url": URL, "price_num": 28.95, "availability": "in_stock",
           "available": True, "size_ml": 100, "sku": "pz-9pm-100"}
    connector = ParfumzentrumConnector(["Afnan 9 PM"], search_func=lambda query: [row])

    async def run():
        found = await connector.discover_products()
        assert len(found) == 1
        assert len(await connector.fetch_offers(URL)) == 1

    asyncio.run(run())


def test_parfumzentrum_rejects_malformed_raw_payload():
    with pytest.raises(ValueError):
        ParfumzentrumConnector().parse_raw("<html>changed markup</html>")
