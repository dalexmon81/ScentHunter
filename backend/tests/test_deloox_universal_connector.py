from pathlib import Path

from app.connectors.deloox import DelooxConnector

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "connectors" / "deloox-product.html"
URL = "https://www.deloox.be/product/123/dior-sauvage-edp-100-ml"


def test_deloox_saved_jsonld_fixture_maps_to_universal_offer():
    connector = DelooxConnector()
    records = connector.parse_raw((URL, FIXTURE.read_text(encoding="utf-8"), "Dior Sauvage"))
    assert len(records) == 1
    record = records[0]
    assert record.store == "deloox"
    assert record.external_product_id == "dlx-100"
    assert record.brand == "Dior"
    assert record.fragrance == "sauvage"
    assert record.concentration == "edp"
    assert record.size_ml == 100
    assert str(record.price) == "89.9"
    assert record.currency == "EUR"
    assert record.availability == "in_stock"
    assert connector.validate_offer(record)[0]


def test_deloox_rejects_malformed_raw_payload():
    import pytest
    with pytest.raises(ValueError):
        DelooxConnector().parse_raw("<html>changed markup</html>")


def test_deloox_discovery_is_injected_and_store_scoped():
    connector = DelooxConnector(
        ["Dior Sauvage"],
        search_func=lambda query: [{
            "name": "Dior Sauvage Eau de Parfum 100 ml",
            "brand": "Dior", "url": URL, "sku": "dlx-100",
            "price_num": 89.90, "currency": "EUR", "availability": "in_stock",
            "size_ml": 100, "concentration": "Eau de Parfum",
        }],
    )
    import asyncio
    async def run():
        rows = await connector.discover_products()
        assert len(rows) == 1
        offers = await connector.fetch_offers("dlx-100")
        assert len(offers) == 1
        assert offers[0].availability == "in_stock"
    asyncio.run(run())
