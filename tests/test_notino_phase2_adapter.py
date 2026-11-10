from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import (
    Base, Brand, Fragrance, ProductVariant, Store, Offer, PriceHistory,
    IngestionRaw,
)
from app.services.notino_phase2_adapter import persist_notino_record


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        brand = Brand(name="Test Brand", slug="test-brand", normalized_name="test brand")
        session.add(brand)
        session.flush()
        fragrance = Fragrance(
            brand_id=brand.id, name="Test Fragrance", slug="test-fragrance",
        )
        session.add(fragrance)
        session.flush()
        variant = ProductVariant(
            fragrance_id=fragrance.id, concentration="EDP", size_ml=100,
            gtin="1234567890123", canonical_key="test|fragrance|edp|100",
        )
        store = Store(
            name="NOTINO.fr", slug="notino-fr", domain="notino.fr",
            country="FR", currency="EUR", status="active",
        )
        session.add_all([variant, store])
        session.flush()
        ids = (store.id, variant.id)
    return engine, ids


def _record(external_id: str, *, price: str = "49.90", **changes):
    record = {
        "external_id": external_id,
        "gtin": "1234567890123",
        "price": price,
        "sale_price": None,
        "currency": "EUR",
        "availability": "in stock",
        "affiliate_url": f"https://notino.fr/p/{external_id}",
    }
    record.update(changes)
    return record


def test_distinct_notino_external_ids_create_distinct_offers_for_same_variant():
    engine, (store_id, variant_id) = _database()
    try:
        with Session(engine) as session, session.begin():
            first = persist_notino_record(
                session, store_id=store_id, raw_record=_record("SKU-ONE"),
            )
            second = persist_notino_record(
                session, store_id=store_id, raw_record=_record("SKU-TWO"),
            )
            assert first.status == second.status == "promoted"
            assert first.offer_id != second.offer_id
            assert first.product_variant_id == second.product_variant_id == variant_id

        with Session(engine) as session:
            offers = session.scalars(select(Offer).order_by(Offer.external_product_id)).all()
            assert len(offers) == 2
            assert {offer.external_product_id for offer in offers} == {"SKU-ONE", "SKU-TWO"}
            assert all(offer.product_variant_id == variant_id for offer in offers)
    finally:
        engine.dispose()


def test_repeat_notino_external_id_updates_same_offer_and_appends_history():
    engine, (store_id, _variant_id) = _database()
    try:
        with Session(engine) as session, session.begin():
            first = persist_notino_record(
                session, store_id=store_id, raw_record=_record("SKU-ONE"),
            )
        with Session(engine) as session, session.begin():
            second = persist_notino_record(
                session, store_id=store_id,
                raw_record=_record("SKU-ONE", price="39.90"),
            )
            assert second.status == "promoted"
            assert second.offer_id == first.offer_id

        with Session(engine) as session:
            offers = session.scalars(select(Offer)).all()
            history = session.scalars(
                select(PriceHistory).where(PriceHistory.offer_id == first.offer_id)
            ).all()
            assert len(offers) == 1
            assert offers[0].price == Decimal("39.90")
            assert len(history) == 2
            assert session.get(IngestionRaw, second.ingestion_raw_id).status == "promoted"
    finally:
        engine.dispose()


def test_unmatched_gtin_stays_pending_and_is_not_published():
    engine, (store_id, _variant_id) = _database()
    try:
        with Session(engine) as session, session.begin():
            result = persist_notino_record(
                session, store_id=store_id,
                raw_record=_record("SKU-UNKNOWN", gtin="9999999999999"),
            )
            assert result.status == "pending"
            assert result.offer_id is None
            assert result.reason == "gtin_not_in_canonical_catalog"

        with Session(engine) as session:
            raw = session.get(IngestionRaw, result.ingestion_raw_id)
            assert raw is not None and raw.status == "pending"
            assert raw.product_variant_id is None
            assert session.scalars(select(Offer)).all() == []
    finally:
        engine.dispose()


def test_unknown_availability_is_matched_but_not_promoted():
    engine, (store_id, _variant_id) = _database()
    try:
        with Session(engine) as session, session.begin():
            result = persist_notino_record(
                session, store_id=store_id,
                raw_record=_record("SKU-PREORDER", availability="preorder"),
            )
            assert result.status == "matched"
            assert result.offer_id is None
            assert result.reason == "availability_not_explicit"

        with Session(engine) as session:
            raw = session.get(IngestionRaw, result.ingestion_raw_id)
            assert raw is not None and raw.status == "matched"
            assert session.scalars(select(Offer)).all() == []
    finally:
        engine.dispose()
