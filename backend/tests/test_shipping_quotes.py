from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Store, StoreShippingRate
from app.services.shipping_quotes import quote_shipping


@pytest.fixture
def shipping_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        store = Store(name="Example", slug="example", currency="EUR")
        session.add(store)
        session.flush()
        now = datetime.now(timezone.utc)
        session.add(StoreShippingRate(
            store_id=store.id, country_code="LU", currency="EUR",
            base_cost=Decimal("7.90"), free_shipping_threshold=Decimal("100.00"),
            status="verified", method="official_page",
            source_url="https://example.test/shipping", evidence_reference="terms-v1",
            captured_at=now, valid_until=now + timedelta(days=7),
        ))
        session.commit()
        yield session
    engine.dispose()


def test_verified_shipping_rate_calculates_landed_total(shipping_session):
    result = quote_shipping(shipping_session, store_slug="example", country_code="LU",
                            order_subtotal="79.00", currency="EUR")
    assert result["status"] == "verified"
    assert result["shipping_cost"] == 7.9
    assert result["total_cost"] == 86.9


def test_free_shipping_threshold_is_applied(shipping_session):
    result = quote_shipping(shipping_session, store_slug="example", country_code="LU",
                            order_subtotal="100.00", currency="EUR")
    assert result["shipping_cost"] == 0.0
    assert result["total_cost"] == 100.0


def test_missing_rate_is_unknown_not_free_shipping(shipping_session):
    result = quote_shipping(shipping_session, store_slug="example", country_code="BE",
                            order_subtotal="30.00")
    assert result["status"] == "unknown"
    assert "shipping_cost" not in result


def test_expired_verified_rate_is_not_used(shipping_session):
    rate = shipping_session.query(StoreShippingRate).one()
    rate.valid_until = datetime.now(timezone.utc) - timedelta(days=1)
    shipping_session.commit()
    result = quote_shipping(shipping_session, store_slug="example", country_code="LU",
                            order_subtotal="30.00")
    assert result["status"] == "stale"
    assert "total_cost" not in result


def test_currency_mismatch_is_not_converted_implicitly(shipping_session):
    result = quote_shipping(shipping_session, store_slug="example", country_code="LU",
                            order_subtotal="30.00", currency="USD")
    assert result["status"] == "unknown"
    assert result["reason"] == "currency_mismatch"


def test_invalid_country_code_is_rejected(shipping_session):
    with pytest.raises(ValueError, match="iso_3166"):
        quote_shipping(shipping_session, store_slug="example", country_code="LUX",
                       order_subtotal="30.00")


def test_estimated_shipping_never_returns_verified_total(shipping_session):
    rate = shipping_session.query(StoreShippingRate).one()
    rate.status = "estimated"
    rate.valid_until = None
    shipping_session.commit()
    result = quote_shipping(shipping_session, store_slug="example", country_code="LU",
                            order_subtotal="30.00")
    assert result["status"] == "estimated"
    assert result["total_cost_estimate"] == 37.9
    assert "total_cost" not in result
