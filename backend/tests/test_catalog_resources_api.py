from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Brand, Fragrance, Offer, ProductVariant, Store
from app.api import catalog_resources as api


@pytest.fixture
def catalog_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'resources.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    brand_id, fragrance_id = uuid4(), uuid4()
    variant_a, variant_b = uuid4(), uuid4()
    store_id = uuid4()
    slug = "sauvage-resources"
    now = datetime.now(timezone.utc)
    with factory.begin() as session:
        session.add(Brand(id=brand_id, name="Dior", slug="dior-resources",
                          normalized_name="dior-resources"))
        session.add(Fragrance(id=fragrance_id, brand_id=brand_id,
                              name="Sauvage", slug=slug, family="aromatic",
                              gender="men"))
        session.add_all([
            ProductVariant(id=variant_a, fragrance_id=fragrance_id,
                           concentration="EDP", size_ml=100,
                           canonical_key="dior|sauvage|edp|100"),
            ProductVariant(id=variant_b, fragrance_id=fragrance_id,
                           concentration="EDT", size_ml=60,
                           canonical_key="dior|sauvage|edt|60"),
        ])
        session.add(Store(id=store_id, name="Notino", slug="notino-resources",
                          country="FR", currency="EUR", status="active"))
        session.add_all([
            Offer(id=uuid4(), store_id=store_id, product_variant_id=variant_a,
                  external_product_id="current", url="https://example.invalid/current",
                  price=Decimal("89.90"), currency="EUR", availability="in_stock",
                  source="test", confidence=Decimal("1.000"), captured_at=now,
                  status="active", publication_status="published"),
            Offer(id=uuid4(), store_id=store_id, product_variant_id=variant_a,
                  external_product_id="expired", url="https://example.invalid/expired",
                  price=Decimal("49.90"), currency="EUR", availability="in_stock",
                  source="test", confidence=Decimal("1.000"),
                  captured_at=now - timedelta(hours=72),
                  status="active", publication_status="published"),
        ])
    monkeypatch.setattr(api, "make_session_factory", lambda: factory)
    yield factory
    engine.dispose()


def test_product_detail_requires_variant_choice_when_multiple(catalog_db):
    result = api.get_product("sauvage-resources")
    assert result["variant_selection_required"] is True
    assert len(result["variants"]) == 2


def test_product_offers_requires_explicit_variant(catalog_db):
    with pytest.raises(HTTPException) as exc:
        api.get_product_offers("sauvage-resources")
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "variant_selection_required"


def test_product_offers_marks_old_prices_for_verification(catalog_db):
    with catalog_db() as session:
        variant_id = session.query(ProductVariant).filter_by(concentration="EDP").one().id
    result = api.get_product_offers("sauvage-resources", variant_id=variant_id)
    assert len(result["offers"]) == 2
    assert result["offers"][0]["is_expired"] is False
    assert result["offers"][1]["is_expired"] is True
    assert result["offers"][1]["label"] == "dato_da_verificare"


def test_brand_and_store_catalog_lists(catalog_db):
    assert api.list_brands(limit=100)["brands"][0]["name"] == "Dior"
    stores = api.list_stores(limit=100)["stores"]
    assert stores[0]["name"] == "Notino"


def test_unknown_product_returns_404(catalog_db):
    with pytest.raises(HTTPException) as exc:
        api.get_product("not-a-real-fragrance")
    assert exc.value.status_code == 404
