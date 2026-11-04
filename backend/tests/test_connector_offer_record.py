from decimal import Decimal

from app.connectors.base import OfferRecord


def test_offer_record_serializes_explicit_packaging():
    record = OfferRecord(
        store="test-shop",
        external_product_id="sku-100",
        brand="Dior",
        fragrance="Sauvage",
        concentration="edp",
        size_ml=100,
        gtin=None,
        title="Dior Sauvage EDP 100 ml",
        url="https://shop.example/item/sku-100",
        price=Decimal("90.00"),
        currency="EUR",
        availability="in_stock",
        captured_at="2026-11-04T10:00:00+00:00",
        source="fixture",
        packaging="tester",
    )

    payload = record.to_dict()

    assert payload["packaging"] == "tester"
    assert payload["sizeMl"] == 100
    assert payload["externalProductId"] == "sku-100"


def test_offer_record_packaging_remains_optional_for_existing_connectors():
    record = OfferRecord(
        store="test-shop",
        external_product_id="sku-101",
        brand="Dior",
        fragrance="Sauvage",
        concentration="edp",
        size_ml=100,
        gtin=None,
        title="Dior Sauvage EDP 100 ml",
        url="https://shop.example/item/sku-101",
        price=Decimal("90.00"),
        currency="EUR",
        availability="in_stock",
        captured_at="2026-11-04T10:00:00+00:00",
        source="fixture",
    )

    assert record.to_dict()["packaging"] is None
