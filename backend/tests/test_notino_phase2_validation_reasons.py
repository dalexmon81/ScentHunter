from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.models import Base, Brand, Fragrance, ProductVariant, Store, Offer, IngestionRaw
from app.services.notino_phase2_adapter import persist_notino_record
from app.services.ingestion_persistence import promote_offer, record_match, stage_raw_offer


def _fixture():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        brand = Brand(name="Validation Brand", slug="validation-brand", normalized_name="validation brand")
        session.add(brand)
        session.flush()
        fragrance = Fragrance(brand_id=brand.id, name="Validation Fragrance", slug="validation-fragrance")
        session.add(fragrance)
        session.flush()
        variant = ProductVariant(
            fragrance_id=fragrance.id, concentration="EDP", size_ml=100,
            gtin="4006381333931", canonical_key="validation|fragrance|edp|100",
        )
        store = Store(
            name="NOTINO.fr", slug="notino-fr", domain="notino.fr",
            country="FR", currency="EUR", status="active",
        )
        legacy_store = Store(
            name="Legacy test store", slug="legacy-test-store", domain="legacy.example",
            country="DE", currency="EUR", status="active",
        )
        session.add_all([variant, store, legacy_store])
        session.flush()
        result = (store.id, legacy_store.id, variant.id)
    return engine, result


def _notino_record(external_id: str, **changes):
    row = {
        "external_id": external_id,
        "gtin": "4006381333931",
        "price": "49.90",
        "sale_price": None,
        "currency": "EUR",
        "availability": "in stock",
        "affiliate_url": f"https://notino.fr/p/{external_id}",
        "captured_at": "2026-11-10T12:00:00Z",
    }
    row.update(changes)
    return row


class NotinoPersistenceValidationTests(unittest.TestCase):
    def test_matched_but_unpublishable_rows_keep_their_rejection_reason(self):
        engine, (notino_store_id, _legacy_store_id, _variant_id) = _fixture()
        cases = [
            ("BAD-PRICE", {"price": "0"}, "invalid_price"),
            ("BAD-CURRENCY", {"currency": "USD"}, "unexpected_currency"),
            ("BAD-URL", {"affiliate_url": "file:///tmp/not-an-offer"}, "invalid_affiliate_url"),
            ("UNKNOWN-STOCK", {"availability": "preorder"}, "availability_not_explicit"),
            ("NO-TIMESTAMP", {"captured_at": ""}, "missing_source_observation_timestamp"),
            ("NAIVE-TIMESTAMP", {"captured_at": "2026-11-10T12:00:00"}, "invalid_source_observation_timestamp"),
        ]
        try:
            with Session(engine) as session, session.begin():
                results = []
                for external_id, changes, expected_reason in cases:
                    result = persist_notino_record(
                        session, store_id=notino_store_id,
                        raw_record=_notino_record(external_id, **changes),
                    )
                    self.assertEqual(result.status, "matched")
                    self.assertEqual(result.reason, expected_reason)
                    results.append((result, expected_reason))
            with Session(engine) as session:
                for result, expected_reason in results:
                    raw = session.get(IngestionRaw, result.ingestion_raw_id)
                    self.assertIsNotNone(raw)
                    self.assertEqual(raw.status, "matched")
                    self.assertEqual(raw.rejection_reason, expected_reason)
                self.assertEqual(session.scalars(select(Offer)).all(), [])
        finally:
            engine.dispose()

    def test_stale_observation_reason_is_persisted_without_replacing_offer(self):
        engine, (notino_store_id, _legacy_store_id, _variant_id) = _fixture()
        try:
            with Session(engine) as session, session.begin():
                newest = persist_notino_record(
                    session, store_id=notino_store_id,
                    raw_record=_notino_record("SKU-STALE", price="25.00", captured_at="2026-11-10T12:10:00Z"),
                )
                stale = persist_notino_record(
                    session, store_id=notino_store_id,
                    raw_record=_notino_record("SKU-STALE", price="70.00", captured_at="2026-11-10T12:05:00Z"),
                )
                self.assertEqual(newest.status, "promoted")
                self.assertEqual(stale.status, "stale")
            with Session(engine) as session:
                raw = session.get(IngestionRaw, stale.ingestion_raw_id)
                offer = session.get(Offer, newest.offer_id)
                self.assertEqual(raw.rejection_reason, "source_observation_not_newer_than_stored_offer")
                self.assertEqual(offer.price, Decimal("25.00"))
        finally:
            engine.dispose()

    def test_legacy_variant_fallback_remains_available_when_requested(self):
        engine, (_notino_store_id, legacy_store_id, variant_id) = _fixture()
        try:
            with Session(engine) as session, session.begin():
                first_raw = stage_raw_offer(
                    session, store_id=legacy_store_id, raw_payload={"id": "LEGACY-A"},
                    external_product_id="LEGACY-A",
                )
                record_match(session, ingestion_raw_id=first_raw, product_variant_id=variant_id, method="legacy_test")
                first_offer = promote_offer(
                    session, ingestion_raw_id=first_raw, price=Decimal("40.00"),
                    currency="EUR", url="https://legacy.example/a",
                    availability="in_stock", source="legacy_test",
                )
                second_raw = stage_raw_offer(
                    session, store_id=legacy_store_id, raw_payload={"id": "LEGACY-B"},
                    external_product_id="LEGACY-B",
                )
                record_match(session, ingestion_raw_id=second_raw, product_variant_id=variant_id, method="legacy_test")
                second_offer = promote_offer(
                    session, ingestion_raw_id=second_raw, price=Decimal("35.00"),
                    currency="EUR", url="https://legacy.example/b",
                    availability="in_stock", source="legacy_test",
                )
                self.assertEqual(first_offer, second_offer)
            with Session(engine) as session:
                offers = session.scalars(select(Offer).where(Offer.store_id == legacy_store_id)).all()
                self.assertEqual(len(offers), 1)
                self.assertEqual(offers[0].external_product_id, "LEGACY-B")
                self.assertEqual(offers[0].price, Decimal("35.00"))
        finally:
            engine.dispose()

    def test_notino_distinct_external_ids_remain_distinct_for_same_variant(self):
        engine, (notino_store_id, _legacy_store_id, variant_id) = _fixture()
        try:
            with Session(engine) as session, session.begin():
                first = persist_notino_record(
                    session, store_id=notino_store_id, raw_record=_notino_record("NOTINO-A"),
                )
                second = persist_notino_record(
                    session, store_id=notino_store_id, raw_record=_notino_record("NOTINO-B"),
                )
                self.assertEqual(first.status, "promoted")
                self.assertEqual(second.status, "promoted")
                self.assertNotEqual(first.offer_id, second.offer_id)
                self.assertEqual(first.product_variant_id, variant_id)
                self.assertEqual(second.product_variant_id, variant_id)
            with Session(engine) as session:
                offers = session.scalars(select(Offer).where(Offer.store_id == notino_store_id)).all()
                self.assertEqual(len(offers), 2)
                self.assertEqual({offer.external_product_id for offer in offers}, {"NOTINO-A", "NOTINO-B"})
        finally:
            engine.dispose()
