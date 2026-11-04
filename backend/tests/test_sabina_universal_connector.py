from pathlib import Path
import asyncio

import pytest

from app.connectors.sabina import SabinaConnector

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "connectors" / "sabina-product.html"
URL = "https://www.sabina.com/it/profumi-uomo/12345-dior-sauvage.html"


def test_sabina_saved_jsonld_fixture_maps_to_universal_offer():
    connector = SabinaConnector()
    records = connector.parse_raw((URL, FIXTURE.read_text(encoding="utf-8")))
    assert records
    # Sabina may expose the selected product-level offer plus separately
    # represented size combinations. Assert the requested variant by its
    # actual size/price evidence rather than assuming one row per page.
    offer = next(record for record in records if record.size_ml == 100)
    signatures = {(record.size_ml, record.price) for record in records}
    assert len(signatures) == len(records)
    assert offer.store == "sabina"
    assert offer.external_product_id == "sab-12345"
    assert offer.brand == "Dior"
    assert offer.fragrance == "sauvage"
    assert offer.concentration == "edp"
    assert offer.size_ml == 100
    assert str(offer.price) == "96.50"
    assert offer.currency == "EUR"
    assert offer.availability == "in_stock"
    assert connector.validate_offer(offer)[0]


def test_sabina_unknown_stock_is_not_invented():
    row = {
        "name": "Dior Sauvage Eau de Parfum 100 ml",
        "brand": "Dior", "url": URL, "price_num": 96.50,
        "currency": "EUR", "availability": "unknown", "size_ml": 100,
    }
    assert SabinaConnector().parse_raw(row)[0].availability == "unknown"


def test_sabina_discovery_uses_injected_search():
    row = {
        "name": "Dior Sauvage Eau de Parfum 100 ml", "brand": "Dior",
        "url": URL, "price_num": 96.50, "currency": "EUR",
        "availability": "in_stock", "size_ml": 100,
    }
    connector = SabinaConnector(["Dior Sauvage"], search_func=lambda query: [row])

    async def run():
        found = await connector.discover_products()
        assert len(found) == 1
        offers = await connector.fetch_offers(URL)
        assert len(offers) == 1

    asyncio.run(run())


def test_sabina_rejects_malformed_raw_payload():
    with pytest.raises(ValueError):
        SabinaConnector().parse_raw("<html>changed markup</html>")
