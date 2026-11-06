from datetime import datetime, timezone
from decimal import Decimal

from app.connectors.base import OfferRecord, validate_offer
from app.models import ProductVariant
from app.services.ingestion_persistence import _ALLOWED_AVAILABILITY


def _offer(currency: str, availability: str = "in_stock") -> OfferRecord:
    return OfferRecord(
        store="example", external_product_id="sku-1", brand="Brand",
        fragrance="Scent", concentration="edp", size_ml=29.57, gtin=None,
        title="Brand Scent EDP 29.57 ml", url="https://shop.example/item",
        price=Decimal("19.90"), currency=currency, availability=availability,
        captured_at=datetime.now(timezone.utc).isoformat(), source="fixture",
    )


def test_connector_contract_accepts_non_eur_currency_codes():
    for currency in ("EUR", "CHF", "GBP", "USD", "JPY"):
        valid, errors = validate_offer(_offer(currency))
        assert valid, (currency, errors)


def test_connector_contract_rejects_malformed_currency_codes():
    for currency in ("eur", "EU", "EURO", "", None):
        valid, errors = validate_offer(_offer(currency))
        assert not valid
        assert "invalid_currency_code" in errors


def test_unknown_stock_is_not_publishable():
    valid, errors = validate_offer(_offer("CHF", "unknown"))
    assert not valid
    assert "invalid_availability" in errors
    assert _ALLOWED_AVAILABILITY == {"in_stock", "out_of_stock", "preorder"}


def test_variant_size_schema_preserves_fractional_millilitres():
    column = ProductVariant.__table__.c.size_ml
    assert isinstance(column.type, __import__("sqlalchemy").Numeric)
    assert column.type.precision == 10
    assert column.type.scale == 4
