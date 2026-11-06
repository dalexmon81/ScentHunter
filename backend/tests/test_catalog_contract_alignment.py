from datetime import datetime, timezone
from decimal import Decimal

from app.connectors.base import OfferRecord, validate_offer, validate_offer_payload
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


def test_unknown_stock_is_evidence_but_not_publishable():
    evidence_valid, evidence_errors = validate_offer(_offer("CHF", "unknown"))
    assert evidence_valid, evidence_errors

    valid, errors = validate_offer_payload(_offer("CHF", "unknown").to_dict())
    assert not valid
    assert "availability_requires_review" in errors
    assert _ALLOWED_AVAILABILITY == {"in_stock", "out_of_stock"}


def test_variant_size_schema_preserves_fractional_millilitres():
    column = ProductVariant.__table__.c.size_ml
    assert isinstance(column.type, __import__("sqlalchemy").Numeric)
    assert column.type.precision == 10
    assert column.type.scale == 4



def test_persisted_payload_uses_the_same_validation_contract():
    payload = _offer("CHF", "preorder").to_dict()
    valid, errors = validate_offer_payload(payload)
    assert valid, errors

    payload["url"] = "https://"
    valid, errors = validate_offer_payload(payload)
    assert not valid
    assert "invalid_https_url" in errors


def test_ingestion_raw_has_partial_unique_guard_for_live_store_products():
    indexes = {index.name: index for index in __import__("app.models", fromlist=["IngestionRaw"]).IngestionRaw.__table__.indexes}
    guard = indexes["uq_ingestion_raw_live_store_external"]
    assert guard.unique is True
    assert {column.name for column in guard.columns} == {"store_id", "external_product_id"}
    predicate = str(guard.dialect_options["sqlite"]["where"])
    assert "pending" in predicate and "unmatched" in predicate and "matched" in predicate
    assert "promoted" not in predicate
