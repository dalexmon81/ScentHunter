import asyncio
from decimal import Decimal

import pytest

from app.connectors import (
    BplatzConnector, OrioudhConnector, ParfumCityConnector, PerfumeMarketConnector,
)

URLS = {
    "perfumemarket": "https://www.perfumemarket.nl/products/dior-sauvage",
    "parfumcity": "https://www.parfumcity.nl/products/dior-sauvage",
    "bplatz": "https://en.bplatz.de/products/dior-sauvage",
    "orioudh": "https://orioudh.com/products/dior-sauvage",
}
CONNECTORS = [
    ("perfumemarket", PerfumeMarketConnector),
    ("parfumcity", ParfumCityConnector),
    ("bplatz", BplatzConnector),
    ("orioudh", OrioudhConnector),
]


def row(store):
    return {
        "store": store,
        "name": "Dior Sauvage Eau de Parfum 100 ml",
        "brand": "Dior",
        "url": URLS[store],
        "price_num": 89.90,
        "currency": "EUR",
        "availability": "in_stock",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "identity": {
            "sku": {"value": f"{store}-sauvage-100", "source": "fixture"},
            "gtin": {"value": "3348901250146", "source": "fixture"},
        },
        "source": {
            "source_name": "Dior Sauvage Eau de Parfum 100 ml",
            "source_brand": "Dior",
            "url": URLS[store],
        },
        "offer": {"price": 89.90, "currency": "EUR", "availability": "in_stock"},
    }


@pytest.mark.parametrize("store,connector_type", CONNECTORS)
def test_missing_store_maps_fixture_row_to_universal_offer(store, connector_type):
    connector = connector_type()
    offers = connector.parse_raw(row(store))
    assert len(offers) == 1
    offer = offers[0]
    assert offer.store == store
    assert offer.brand == "Dior"
    assert offer.size_ml == 100
    assert offer.price == Decimal("89.9")
    assert offer.currency == "EUR"
    assert offer.availability == "in_stock"
    assert offer.external_product_id == f"{store}-sauvage-100"
    assert connector.validate_offer(offer)[0]


@pytest.mark.parametrize("store,connector_type", CONNECTORS)
def test_missing_store_does_not_invent_unknown_stock(store, connector_type):
    payload = row(store)
    payload["offer"]["availability"] = "unknown"
    payload["availability"] = "unknown"
    payload["available"] = None
    offer = connector_type().parse_raw(payload)[0]
    assert offer.availability == "unknown"


@pytest.mark.parametrize("store,connector_type", CONNECTORS)
def test_missing_store_discovery_uses_injected_legacy_search(store, connector_type):
    connector = connector_type(
        discovery_terms=["Dior Sauvage"],
        search_func=lambda query: [row(store)],
    )

    async def run():
        found = await connector.discover_products()
        assert len(found) == 1
        offers = await connector.fetch_offers(URLS[store])
        assert len(offers) == 1

    asyncio.run(run())


@pytest.mark.parametrize("store,connector_type", CONNECTORS)
def test_missing_store_rejects_malformed_payload(store, connector_type):
    with pytest.raises(ValueError):
        connector_type().parse_raw("<html>not a parsed product</html>")
