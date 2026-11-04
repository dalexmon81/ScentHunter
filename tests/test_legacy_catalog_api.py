from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base, Brand, Fragrance, LegacyProductIdMap, Offer,
    ProductVariant, Store,
)
from app.api.legacy_catalog import legacy_product_offers


def _catalog_factory(tmp_path, *, offer_status="active", store_status="active"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-bridge.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    brand_id, fragrance_id, variant_id = uuid4(), uuid4(), uuid4()
    store_id, offer_id = uuid4(), uuid4()
    with factory() as session:
        session.add(Brand(
            id=brand_id, name="Test Brand", slug="test-brand",
            normalized_name="test brand",
        ))
        session.add(Fragrance(
            id=fragrance_id, brand_id=brand_id, name="Test Fragrance",
            slug="test-fragrance",
        ))
        session.add(ProductVariant(
            id=variant_id, fragrance_id=fragrance_id, concentration="EDP",
            size_ml=100, canonical_key="test brand|test fragrance|edp|100",
        ))
        session.add(Store(
            id=store_id, name="Bplatz", slug="bplatz", currency="EUR",
            status=store_status,
        ))
        session.add(LegacyProductIdMap(
            legacy_product_id="SH-TEST-1", fragrance_id=fragrance_id,
        ))
        session.add(Offer(
            id=offer_id, store_id=store_id, product_variant_id=variant_id,
            external_product_id="sku-1",
            url="https://shop.example/test-fragrance",
            price=Decimal("79.90"), currency="EUR",
            availability="in_stock", source="test", status=offer_status,
        ))
        session.commit()
    return factory, offer_id


def test_legacy_product_bridge_returns_only_persisted_offer_uuid(tmp_path):
    factory, offer_id = _catalog_factory(tmp_path)

    result = legacy_product_offers("SH-TEST-1", session_factory=factory)

    assert result["legacy_product_id"] == "SH-TEST-1"
    assert len(result["offers"]) == 1
    offer = result["offers"][0]
    assert offer["phase2_offer_id"] == str(offer_id)
    assert offer["store"] == "bplatz"
    assert offer["url"] == "https://shop.example/test-fragrance"
    assert offer["price"] == 79.9
    assert offer["currency"] == "EUR"
    assert offer["availability"] == "in_stock"
    assert offer["size_ml"] == 100
    assert offer["captured_at"]


def test_legacy_product_bridge_hides_inactive_offer_or_store(tmp_path):
    inactive_offer_factory, _ = _catalog_factory(
        tmp_path / "offer", offer_status="inactive",
    )
    inactive_store_factory, _ = _catalog_factory(
        tmp_path / "store", store_status="inactive",
    )

    assert legacy_product_offers(
        "SH-TEST-1", session_factory=inactive_offer_factory,
    )["offers"] == []
    assert legacy_product_offers(
        "SH-TEST-1", session_factory=inactive_store_factory,
    )["offers"] == []
