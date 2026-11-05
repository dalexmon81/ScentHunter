from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.legacy_catalog import legacy_product_offers
from app.models import (
    Base, Brand, Fragrance, LegacyProductIdMap, Offer, ProductVariant, Store,
)


def _catalog_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-bridge.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    brand_id, fragrance_id, variant_id = uuid4(), uuid4(), uuid4()
    store_id, offer_id = uuid4(), uuid4()
    with factory() as session:
        session.add(Brand(id=brand_id, name="Dior", slug="dior", normalized_name="dior"))
        session.add(Fragrance(
            id=fragrance_id, brand_id=brand_id, name="Sauvage", slug="sauvage",
        ))
        session.add(ProductVariant(
            id=variant_id, fragrance_id=fragrance_id, concentration="EDP",
            size_ml=100, canonical_key="dior|sauvage|edp|100",
        ))
        session.add(Store(
            id=store_id, name="Notino", slug="notino", currency="EUR", status="active",
        ))
        session.add(LegacyProductIdMap(
            legacy_product_id="legacy-123", fragrance_id=fragrance_id,
        ))
        session.add(Offer(
            id=offer_id, store_id=store_id, product_variant_id=variant_id,
            external_product_id="sku-123", url="https://notino.example/sauvage",
            price=Decimal("99.90"), currency="EUR", availability="in_stock",
            source="fixture", status="active",
        ))
        session.commit()
    return factory, offer_id


def test_legacy_bridge_returns_real_phase2_offer_uuid_and_variant(tmp_path):
    factory, offer_id = _catalog_factory(tmp_path)
    result = legacy_product_offers("legacy-123", session_factory=factory)
    assert result["legacy_product_id"] == "legacy-123"
    assert len(result["offers"]) == 1
    row = result["offers"][0]
    assert row["phase2_offer_id"] == str(offer_id)
    assert row["store"] == "notino"
    assert row["url"] == "https://notino.example/sauvage"
    assert row["price"] == 99.9
    assert row["currency"] == "EUR"
    assert row["availability"] == "in_stock"
    assert isinstance(row["captured_at"], str)
    assert row["size_ml"] == 100


def test_legacy_bridge_returns_no_offers_without_explicit_mapping(tmp_path):
    factory, _ = _catalog_factory(tmp_path)
    result = legacy_product_offers("not-a-mapped-id", session_factory=factory)
    assert result == {"legacy_product_id": "not-a-mapped-id", "offers": []}


def test_legacy_bridge_excludes_inactive_offer_and_store(tmp_path):
    factory, offer_id = _catalog_factory(tmp_path)
    with factory() as session:
        from app.models import Offer, Store
        offer = session.get(Offer, offer_id)
        offer.status = "stale"
        session.commit()
    assert legacy_product_offers("legacy-123", session_factory=factory)["offers"] == []


def test_legacy_bridge_rejects_invalid_legacy_id():
    with pytest.raises(HTTPException) as exc:
        legacy_product_offers("")
    assert exc.value.status_code == 400


def test_legacy_bridge_excludes_inactive_store(tmp_path):
    factory, _ = _catalog_factory(tmp_path)
    with factory() as session:
        from app.models import Store
        store = session.query(Store).filter_by(slug="notino").one()
        store.status = "quarantined"
        session.commit()
    assert legacy_product_offers("legacy-123", session_factory=factory)["offers"] == []
