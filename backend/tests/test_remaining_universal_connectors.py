import asyncio
from decimal import Decimal
from datetime import datetime, timezone

import pytest

from app.connectors import (
    BplatzConnector, OrioudhConnector, ParfumCityConnector, PerfumeMarketConnector,
)
from app.connectors.base import OfferRecord

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
            "sku": None,
            "gtin": None,
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
    assert offer.external_product_id == URLS[store]  # URL fallback; no invented SKU/GTIN.
    assert offer.gtin is None
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


@pytest.mark.parametrize("store,connector_type", CONNECTORS)
def test_refresh_resolves_variant_offer_id_to_product_url(store, connector_type):
    requested = []
    def page_loader(url, query):
        requested.append((url, query))
        return row(store)

    connector = connector_type(page_loader=page_loader)
    prior = OfferRecord(
        store=store,
        external_product_id="variant-id-from-retailer",
        brand="Dior",
        fragrance="sauvage",
        concentration="edp",
        size_ml=100,
        gtin=None,
        title="Dior Sauvage Eau de Parfum 100 ml",
        url=URLS[store],
        price=Decimal("99.90"),
        currency="EUR",
        availability="unknown",
        captured_at=datetime.now(timezone.utc).isoformat(),
        source="fixture",
        external_offer_id="variant-id-from-retailer",
    )
    connector._offers[prior.external_product_id] = prior

    async def run():
        refreshed = await connector.fetch_price_and_stock("variant-id-from-retailer")
        assert requested == [(URLS[store], "dior-sauvage")]
        assert refreshed is not None
        assert refreshed.url == URLS[store]
        assert refreshed.price == Decimal("89.90")
        assert refreshed.availability == "in_stock"

    asyncio.run(run())
