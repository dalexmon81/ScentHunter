from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select, event
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.models import (
    Brand, Fragrance, ProductVariant, Store, IngestionRaw, Offer,
    PriceHistory, MatchAudit, LegacyProductIdMap, LegacyVariantIdMap,
)
from app.services.ingestion_persistence import (
    PromotionRejected, stage_raw_offer, record_legacy_match,
    resolve_legacy_ids, promote_offer,
)


def _migrated_database(tmp_path):
    db_path = (tmp_path / "phase2-migration-test.sqlite3").resolve()
    db_url = "sqlite:///" + db_path.as_posix()
    env = os.environ.copy()
    env["SCENTHUNTER_CATALOG_DATABASE_URL"] = db_url
    env["PYTHONPATH"] = str(BACKEND) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "0002_ingestion_raw"],
        cwd=BACKEND, env=env, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, (
        "Alembic upgrade failed\nSTDOUT:\n" + result.stdout + "\nSTDERR:\n" + result.stderr
    )
    engine = create_engine(db_url)
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
    return engine, result.stdout + result.stderr


def _seed_canonical_rows(session, *, create_legacy_maps=True):
    store = Store(name="Bplatz", slug="bplatz", currency="EUR", status="active")
    brand = Brand(name="French Avenue", slug="french-avenue", normalized_name="french avenue")
    session.add_all([store, brand])
    session.flush()
    fragrance = Fragrance(brand_id=brand.id, name="Liquid Brun", slug="liquid-brun")
    session.add(fragrance)
    session.flush()
    variant = ProductVariant(
        fragrance_id=fragrance.id, concentration="EDP", size_ml=100,
        canonical_key="french-avenue|liquid-brun|edp|100",
    )
    session.add(variant)
    session.flush()
    if create_legacy_maps:
        session.add_all([
            LegacyProductIdMap(legacy_product_id="SH-0030", fragrance_id=fragrance.id),
            LegacyVariantIdMap(
                legacy_variant_id="VAR-f87146c82d167f4c",
                product_variant_id=variant.id,
            ),
        ])
        session.flush()
    return store.id, fragrance.id, variant.id


def _real_bplatz_components():
    from scrapers.bplatz.scraper import parse_product_html
    from scenthunter_next_engine.next_engine_service import NextEngineService
    from scenthunter_next_engine.offer_normalizer import normalize_offer

    fixture = ROOT / "tests/fixtures/bplatz/liquid-brun-54015243419916.raw.html"
    meta = json.loads((ROOT / "tests/fixtures/bplatz/liquid-brun-54015243419916.meta.json").read_text())
    parsed = parse_product_html(
        fixture.read_text(encoding="utf-8"), meta["url_final"],
        "French Avenue Liquid Brun",
    )
    assert parsed is not None
    record = {
        "raw_name": parsed["name"], "brand_raw": parsed["brand"],
        "size_ml": parsed["size_ml"], "price": parsed["price_num"],
        "currency": parsed["offer"]["currency"], "product_url": parsed["url"],
        "availability": parsed["availability"], "sku": parsed["sku"], "gtin": parsed["gtin"],
    }
    normalized = normalize_offer(record, retailer="Bplatz", currency_default="EUR")
    matcher = NextEngineService.from_catalog_file(ROOT / "backend/product_catalog.json")
    aggregation = matcher.process_offers([normalized])
    assert aggregation.matched_offer_count == 1
    assert len(aggregation.groups) == 1
    group = aggregation.groups[0]
    assert group.canonical_product_id == "SH-0030"
    assert group.canonical_variant_id == "VAR-f87146c82d167f4c"
    return parsed, record, normalized, group


def test_alembic_0002_migration_creates_required_schema(tmp_path):
    engine, output = _migrated_database(tmp_path)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {
            "brands", "fragrances", "product_variants", "stores", "offers",
            "price_history", "match_audit", "ingestion_runs", "ingestion_raw",
            "legacy_product_id_map", "legacy_variant_id_map", "alembic_version",
        }.issubset(tables)
        raw_columns = {column["name"] for column in inspector.get_columns("ingestion_raw")}
        assert {"legacy_product_id", "legacy_variant_id", "product_variant_id", "status"}.issubset(raw_columns)
        offer_columns = {column["name"] for column in inspector.get_columns("offers")}
        assert "ingestion_raw_id" in offer_columns
        assert inspector.get_pk_constraint("legacy_product_id_map")["constrained_columns"] == ["legacy_product_id"]
        assert inspector.get_pk_constraint("legacy_variant_id_map")["constrained_columns"] == ["legacy_variant_id"]
        with engine.connect() as connection:
            revision = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
        assert revision == "0002_ingestion_raw"
        print("ALEMBIC_REVISION=0002_ingestion_raw")
        print("MIGRATION_TABLES=OK")
    finally:
        engine.dispose()


def test_real_bplatz_pipeline_resolves_legacy_ids_and_promotes_after_migration(tmp_path):
    parsed, record, normalized, group = _real_bplatz_components()
    engine, _ = _migrated_database(tmp_path)
    try:
        with Session(engine) as session, session.begin():
            store_id, fragrance_id, variant_id = _seed_canonical_rows(session)
            raw_id = stage_raw_offer(
                session, store_id=store_id, raw_payload=record,
                external_product_id=parsed["sku"],
            )
            resolved = record_legacy_match(
                session, ingestion_raw_id=raw_id,
                legacy_product_id=group.canonical_product_id,
                legacy_variant_id=group.canonical_variant_id,
                method="real_next_engine_matcher", confidence=Decimal("0.990"),
            )
            assert resolved is not None
            assert resolved.fragrance_id == fragrance_id
            assert resolved.product_variant_id == variant_id
            offer_id = promote_offer(
                session, ingestion_raw_id=raw_id, price=normalized.price,
                currency=normalized.currency, url=normalized.product_url,
                availability=normalized.availability, source="bplatz_jsonld",
                confidence=Decimal("0.990"),
            )
            print(f"LEGACY_PRODUCT_ID={group.canonical_product_id}")
            print(f"LEGACY_VARIANT_ID={group.canonical_variant_id}")
            print(f"RESOLVED_FRAGRANCE_UUID={resolved.fragrance_id}")
            print(f"RESOLVED_VARIANT_UUID={resolved.product_variant_id}")
            print("PROMOTION=SUCCESS")
        with Session(engine) as session:
            offer = session.get(Offer, offer_id)
            raw = session.get(IngestionRaw, raw_id)
            assert offer is not None and offer.product_variant_id == variant_id
            assert offer.ingestion_raw_id == raw_id
            assert raw is not None and raw.status == "promoted"
            assert raw.legacy_product_id == "SH-0030"
            assert raw.legacy_variant_id == "VAR-f87146c82d167f4c"
            assert session.scalar(select(PriceHistory).where(PriceHistory.offer_id == offer_id))
            assert session.scalar(select(MatchAudit).where(MatchAudit.offer_id == offer_id))
            assert session.scalar(select(Offer.id)) == offer_id
    finally:
        engine.dispose()


def test_missing_legacy_uuid_mapping_stays_in_staging_and_cannot_promote(tmp_path):
    parsed, record, normalized, group = _real_bplatz_components()
    engine, _ = _migrated_database(tmp_path)
    try:
        with Session(engine) as session, session.begin():
            store_id, _fragrance_id, _variant_id = _seed_canonical_rows(
                session, create_legacy_maps=False,
            )
            raw_id = stage_raw_offer(
                session, store_id=store_id, raw_payload=record,
                external_product_id=parsed["sku"],
            )
            resolved = resolve_legacy_ids(
                session, legacy_product_id=group.canonical_product_id,
                legacy_variant_id=group.canonical_variant_id,
            )
            assert resolved is None
            recorded = record_legacy_match(
                session, ingestion_raw_id=raw_id,
                legacy_product_id=group.canonical_product_id,
                legacy_variant_id=group.canonical_variant_id,
                method="real_next_engine_matcher", confidence=Decimal("0.990"),
            )
            assert recorded is None
            with pytest.raises(PromotionRejected):
                promote_offer(
                    session, ingestion_raw_id=raw_id, price=normalized.price,
                    currency=normalized.currency, url=normalized.product_url,
                    availability=normalized.availability, source="bplatz_jsonld",
                )
        with Session(engine) as session:
            raw = session.get(IngestionRaw, raw_id)
            assert raw is not None
            assert raw.status == "unmatched"
            assert raw.product_variant_id is None
            assert raw.legacy_product_id == "SH-0030"
            assert raw.legacy_variant_id == "VAR-f87146c82d167f4c"
            assert session.scalar(select(Offer.id)) is None
            print("NEGATIVE_STATUS=unmatched")
            print("NEGATIVE_VARIANT_UUID=NULL")
            print("NEGATIVE_OFFERS=0")
    finally:
        engine.dispose()


@pytest.mark.parametrize("changes", [
    {"price": Decimal("0")},
    {"currency": "eur"},
    {"url": "file:///tmp/not-http"},
    {"availability": "unknown"},
])
def test_invalid_offer_data_still_blocks_promotion_after_legacy_resolution(tmp_path, changes):
    parsed, record, normalized, group = _real_bplatz_components()
    engine, _ = _migrated_database(tmp_path)
    try:
        with Session(engine) as session, session.begin():
            store_id, _fragrance_id, _variant_id = _seed_canonical_rows(session)
            raw_id = stage_raw_offer(session, store_id=store_id, raw_payload=record)
            resolved = record_legacy_match(
                session, ingestion_raw_id=raw_id,
                legacy_product_id=group.canonical_product_id,
                legacy_variant_id=group.canonical_variant_id,
                method="real_next_engine_matcher",
            )
            assert resolved is not None
            values = dict(
                price=normalized.price, currency=normalized.currency,
                url=normalized.product_url, availability=normalized.availability,
                source="bplatz_jsonld",
            )
            values.update(changes)
            with pytest.raises(PromotionRejected):
                promote_offer(session, ingestion_raw_id=raw_id, **values)
        with Session(engine) as session:
            assert session.scalar(select(Offer.id)) is None
            assert session.get(IngestionRaw, raw_id).status == "matched"
    finally:
        engine.dispose()
