from __future__ import annotations

from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy import event
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.models import (
    Base, Brand, Fragrance, ProductVariant, Store, Offer, IngestionRaw,
    LegacyProductIdMap, LegacyVariantIdMap,
)
from app.services.notino_phase2_adapter import persist_notino_record
from app.services.ingestion_persistence import promote_offer, record_match, stage_raw_offer
from scripts.import_notino_phase2_persistent import (
    _seed_canonical_catalog, _stage_unmatched_rows_bulk,
)
from scripts.seed_catalog import stable_id


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
    def test_existing_canonical_seed_skips_full_reseed_and_backfills_gtin(self):
        with tempfile.TemporaryDirectory() as temp:
            catalog_path = Path(temp) / "catalog.json"
            catalog_path.write_text(json.dumps({
                "brands": [],
                "products": [{
                    "product_id": "CATALOG-PRODUCT",
                    "brand_name": "Mapped Brand",
                    "canonical_name": "Mapped Fragrance",
                }],
                "variants": [{
                    "variant_id": "CATALOG-VARIANT",
                    "product_id": "CATALOG-PRODUCT",
                    "size_ml": 100,
                    "concentration": "EDP",
                    "gtins": ["4006381333931"],
                }],
            }), encoding="utf-8")
            engine = create_engine(f"sqlite:///{Path(temp) / 'notino.sqlite3'}")
            Base.metadata.create_all(engine)
            try:
                with Session(engine) as session, session.begin():
                    brand = Brand(
                        name="Mapped Brand", slug="mapped-brand",
                        normalized_name="mapped brand",
                    )
                    session.add(brand)
                    session.flush()
                    fragrance = Fragrance(
                        id=stable_id("fragrance", "CATALOG-PRODUCT"),
                        brand_id=brand.id, name="Mapped Fragrance",
                        slug="mapped-fragrance",
                    )
                    variant = ProductVariant(
                        id=stable_id("variant", "CATALOG-VARIANT"),
                        fragrance_id=fragrance.id, concentration="EDP",
                        size_ml=100, gtin=None,
                        canonical_key="mapped|fragrance|edp|100",
                    )
                    session.add_all([fragrance, variant])
                    session.flush()
                    session.add_all([
                        LegacyProductIdMap(
                            legacy_product_id="CATALOG-PRODUCT",
                            fragrance_id=fragrance.id,
                        ),
                        LegacyVariantIdMap(
                            legacy_variant_id="CATALOG-VARIANT",
                            product_variant_id=variant.id,
                        ),
                    ])

                self.assertFalse(_seed_canonical_catalog(engine, catalog_path))
                with Session(engine) as session:
                    variant = session.get(
                        ProductVariant, stable_id("variant", "CATALOG-VARIANT"),
                    )
                    self.assertEqual(variant.gtin, "4006381333931")
            finally:
                engine.dispose()

    def test_unmatched_rows_are_staged_with_one_bulk_insert(self):
        engine, (notino_store_id, _legacy_store_id, _variant_id) = _fixture()
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, executemany):
            if statement.lstrip().upper().startswith("INSERT INTO INGESTION_RAW"):
                statements.append(executemany)

        event.listen(engine, "before_cursor_execute", capture)
        try:
            with Session(engine) as session, session.begin():
                _stage_unmatched_rows_bulk(session, notino_store_id, [
                    {
                        "external_product_id": "UNKNOWN-A",
                        "raw_payload": {"gtin": "4006381333931"},
                        "match_method": "notino_exact_gtin",
                        "reason": "gtin_not_in_canonical_catalog",
                    },
                    {
                        "external_product_id": "UNKNOWN-B",
                        "raw_payload": {"gtin": "invalid"},
                        "match_method": "notino_gtin_check_digit",
                        "reason": "invalid_gtin_check_digit",
                    },
                ])
            with Session(engine) as session:
                staged = session.scalars(
                    select(IngestionRaw).where(IngestionRaw.store_id == notino_store_id)
                ).all()
                self.assertEqual(len(staged), 2)
                self.assertEqual({row.status for row in staged}, {"pending"})
                self.assertEqual(
                    {row.rejection_reason for row in staged},
                    {"gtin_not_in_canonical_catalog", "invalid_gtin_check_digit"},
                )
                self.assertTrue(all(row.product_variant_id is None for row in staged))
            self.assertEqual(statements, [True])
        finally:
            event.remove(engine, "before_cursor_execute", capture)
            engine.dispose()

    def test_persistent_verifier_checks_price_url_and_canonical_mapping(self):
        from scripts import verify_notino_phase2_persistent

        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "notino.sqlite3"
            engine = create_engine(f"sqlite:///{database}")
            Base.metadata.create_all(engine)
            try:
                with Session(engine) as session, session.begin():
                    brand = Brand(name="Mapped Brand", slug="mapped-brand", normalized_name="mapped brand")
                    session.add(brand)
                    session.flush()
                    fragrance = Fragrance(brand_id=brand.id, name="Mapped Fragrance", slug="mapped-fragrance")
                    session.add(fragrance)
                    session.flush()
                    variant = ProductVariant(
                        fragrance_id=fragrance.id, concentration="EDP", size_ml=100,
                        gtin="4006381333931", canonical_key="mapped|fragrance|edp|100",
                    )
                    store = Store(
                        name="NOTINO.fr", slug="notino-fr", domain="notino.fr",
                        country="FR", currency="EUR", status="active",
                    )
                    session.add_all([variant, store])
                    session.flush()
                    session.add(LegacyProductIdMap(
                        legacy_product_id="mapped-product", fragrance_id=fragrance.id,
                    ))
                    session.flush()
                    persisted = persist_notino_record(
                        session, store_id=store.id,
                        raw_record=_notino_record("MAPPED-SKU"),
                    )
                    self.assertEqual(persisted.status, "promoted")
                metrics = verify_notino_phase2_persistent._metrics(database)
                self.assertEqual(metrics["offers"], 1)
                self.assertEqual(metrics["price_history"], 1)
                self.assertEqual(metrics["distinct_matched_variants"], 1)
                self.assertEqual(metrics["duplicate_external_ids"], 0)
                self.assertEqual(metrics["invalid_offers"], 0)
                from app.services.notino_phase2_search import search_notino_phase2
                previous_database = os.environ.get("NOTINO_PHASE2_DATABASE")
                os.environ["NOTINO_PHASE2_DATABASE"] = str(database)
                try:
                    offers = search_notino_phase2("Mapped Fragrance")
                finally:
                    if previous_database is None:
                        os.environ.pop("NOTINO_PHASE2_DATABASE", None)
                    else:
                        os.environ["NOTINO_PHASE2_DATABASE"] = previous_database
                self.assertEqual(len(offers), 1)
                self.assertEqual(offers[0]["currency"], "EUR")
                self.assertEqual(offers[0]["availability"], "in_stock")
                self.assertEqual(offers[0]["source"], "cj_notino_fr_feed")
            finally:
                engine.dispose()

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


class NotinoFeedMoneyParserTests(unittest.TestCase):
    def test_money_parser_accepts_currency_with_or_without_space(self):
        from scripts.import_notino_phase2_persistent import money

        self.assertEqual(money("36.70 EUR"), (Decimal("36.70"), "EUR"))
        self.assertEqual(money("36,70 EUR"), (Decimal("36.70"), "EUR"))
        self.assertEqual(money("1.234,56 EUR"), (Decimal("1234.56"), "EUR"))
        self.assertEqual(money("36.70EUR"), (Decimal("36.70"), "EUR"))

    def test_money_parser_rejects_missing_or_invalid_amount(self):
        from scripts.import_notino_phase2_persistent import money

        self.assertEqual(money(""), (None, None))
        self.assertEqual(money("not a price"), (None, None))
