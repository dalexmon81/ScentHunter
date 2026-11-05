from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select, event, delete
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.models import (
    Store, IngestionRaw, Offer, PriceHistory, MatchAudit,
    LegacyProductIdMap, LegacyVariantIdMap,
)
from app.services.ingestion_persistence import (
    PromotionRejected, stage_raw_offer, record_legacy_match,
    resolve_legacy_ids, promote_offer,
)

LEGACY_PRODUCT_ID = "SH-0030"
LEGACY_VARIANT_ID = "VAR-f87146c82d167f4c"


def _migrated_database(tmp_path):
    db_path = (tmp_path / "phase2-migration-test.sqlite3").resolve()
    db_url = "sqlite:///" + db_path.as_posix()
    env = os.environ.copy()
    env["SCENTHUNTER_CATALOG_DATABASE_URL"] = db_url
    env["PYTHONPATH"] = str(BACKEND) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND, env=env, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, (
        "Alembic upgrade failed\nSTDOUT:\n" + result.stdout + "\nSTDERR:\n" + result.stderr
    )
    engine = create_engine(db_url)
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
    return engine, db_url, result.stdout + result.stderr


def _seed_real_catalog(db_url):
    env = os.environ.copy()
    env["SCENTHUNTER_CATALOG_DATABASE_URL"] = db_url
    env["PYTHONPATH"] = str(BACKEND) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [
            sys.executable, str(BACKEND / "scripts/seed_catalog.py"),
            "--catalog", str(BACKEND / "product_catalog.json"), "--apply", "--seed-bplatz-store",
        ],
        cwd=ROOT, env=env, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, (
        "Real catalog seed failed\nSTDOUT:\n" + result.stdout + "\nSTDERR:\n" + result.stderr
    )
    report = json.loads(result.stdout)
    assert report["status"] == "seeded"
    assert report["database_written"] is True
    return report


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
    assert group.canonical_product_id == LEGACY_PRODUCT_ID
    assert group.canonical_variant_id == LEGACY_VARIANT_ID
    return parsed, record, normalized, group


def _create_bplatz_store(session):
    store = session.scalar(select(Store).where(Store.slug == "bplatz"))
    if store is None:
        store = Store(
            name="Bplatz", slug="bplatz", domain="bplatz.de",
            country="DE", currency="EUR", status="active",
        )
        session.add(store)
        session.flush()
    return store.id


def test_alembic_0002_migration_creates_required_schema(tmp_path):
    engine, _db_url, _ = _migrated_database(tmp_path)
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
        with engine.connect() as connection:
            revision = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
        assert revision == "0003_store_domain"
        print("ALEMBIC_REVISION=0003_store_domain")
        print("MIGRATION_TABLES=OK")
    finally:
        engine.dispose()


def test_real_bplatz_pipeline_resolves_seeded_legacy_ids_and_promotes(tmp_path):
    parsed, record, normalized, group = _real_bplatz_components()
    engine, db_url, _ = _migrated_database(tmp_path)
    try:
        seed_report = _seed_real_catalog(db_url)
        assert seed_report["database_counts"]["legacy_product_id_map"] >= 1
        assert seed_report["database_counts"]["legacy_variant_id_map"] >= 1
        with Session(engine) as session, session.begin():
            store_id = _create_bplatz_store(session)
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
            assert offer is not None and offer.product_variant_id == resolved.product_variant_id
            assert offer.ingestion_raw_id == raw_id
            assert raw is not None and raw.status == "promoted"
            assert raw.legacy_product_id == LEGACY_PRODUCT_ID
            assert raw.legacy_variant_id == LEGACY_VARIANT_ID
            assert session.scalar(select(PriceHistory).where(PriceHistory.offer_id == offer_id))
            assert session.scalar(select(MatchAudit).where(MatchAudit.offer_id == offer_id))
            assert session.scalar(select(Offer.id)) == offer_id
    finally:
        engine.dispose()


def test_missing_legacy_uuid_mapping_stays_in_staging_and_cannot_promote(tmp_path):
    parsed, record, normalized, group = _real_bplatz_components()
    engine, db_url, _ = _migrated_database(tmp_path)
    try:
        _seed_real_catalog(db_url)
        with Session(engine) as session, session.begin():
            store_id = _create_bplatz_store(session)
            session.execute(delete(LegacyProductIdMap).where(
                LegacyProductIdMap.legacy_product_id == group.canonical_product_id))
            session.execute(delete(LegacyVariantIdMap).where(
                LegacyVariantIdMap.legacy_variant_id == group.canonical_variant_id))
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
            assert raw is not None and raw.status == "unmatched"
            assert raw.product_variant_id is None
            assert raw.legacy_product_id == LEGACY_PRODUCT_ID
            assert raw.legacy_variant_id == LEGACY_VARIANT_ID
            assert session.scalar(select(Offer.id)) is None
            print("NEGATIVE_STATUS=unmatched")
            print("NEGATIVE_VARIANT_UUID=NULL")
            print("NEGATIVE_OFFERS=0")
    finally:
        engine.dispose()


def test_invalid_offer_fields_block_promotion_after_real_legacy_resolution(tmp_path):
    parsed, record, normalized, group = _real_bplatz_components()
    engine, db_url, _ = _migrated_database(tmp_path)
    try:
        _seed_real_catalog(db_url)
        invalid_values = [
            {"price": Decimal("0")},
            {"currency": "eur"},
            {"url": "file:///tmp/not-http"},
            {"availability": "unknown"},
        ]
        with Session(engine) as session, session.begin():
            store_id = _create_bplatz_store(session)
            for changes in invalid_values:
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
            assert session.scalar(select(IngestionRaw.status).where(IngestionRaw.status == "matched")) == "matched"
    finally:
        engine.dispose()



def test_bplatz_phase2_adapter_runs_real_persistence_contract(tmp_path):
    from app.services.bplatz_phase2_adapter import persist_bplatz_record
    from scenthunter_next_engine.next_engine_service import NextEngineService

    _parsed, record, normalized, group = _real_bplatz_components()
    engine, db_url, _ = _migrated_database(tmp_path)
    try:
        seed_report = _seed_real_catalog(db_url)
        assert seed_report["database_counts"]["legacy_product_id_map"] >= 1
        assert seed_report["database_counts"]["legacy_variant_id_map"] >= 1
        matcher = NextEngineService.from_catalog_file(BACKEND / "product_catalog.json")

        with Session(engine) as session, session.begin():
            store_id = _create_bplatz_store(session)
            result = persist_bplatz_record(
                session, store_id=store_id, raw_record=record, matcher=matcher,
            )
            assert result.status == "promoted"
            assert result.offer_id is not None
            assert result.fragrance_id is not None
            assert result.product_variant_id is not None
            assert result.reason is None

        with Session(engine) as session:
            offer = session.get(Offer, result.offer_id)
            raw = session.get(IngestionRaw, result.ingestion_raw_id)
            assert offer is not None
            assert offer.store_id == store_id
            assert offer.product_variant_id == result.product_variant_id
            assert offer.price == normalized.price
            assert offer.currency == "EUR"
            assert offer.url == normalized.product_url
            assert offer.availability == "in_stock"
            store = session.get(Store, offer.store_id)
            assert store is not None
            assert (store.name, store.domain, store.country, store.currency, store.status) == (
                "Bplatz", "bplatz.de", "DE", "EUR", "active",
            )
            assert raw is not None and raw.status == "promoted"
            assert raw.legacy_product_id == group.canonical_product_id
            assert raw.legacy_variant_id == group.canonical_variant_id
            assert session.scalar(select(PriceHistory).where(
                PriceHistory.offer_id == result.offer_id
            )) is not None
            assert session.scalar(select(MatchAudit).where(
                MatchAudit.offer_id == result.offer_id
            )) is not None
            assert session.scalar(select(Offer.id)) == result.offer_id
    finally:
        engine.dispose()


def test_bplatz_phase2_repeat_hydration_updates_one_offer_and_price_history(tmp_path):
    from app.services.bplatz_phase2_adapter import persist_bplatz_record
    from scenthunter_next_engine.next_engine_service import NextEngineService

    _parsed, record, normalized, _group = _real_bplatz_components()
    engine, db_url, _ = _migrated_database(tmp_path)
    try:
        _seed_real_catalog(db_url)
        matcher = NextEngineService.from_catalog_file(BACKEND / "product_catalog.json")
        with Session(engine) as session, session.begin():
            store_id = _create_bplatz_store(session)
            first = persist_bplatz_record(
                session, store_id=store_id, raw_record=dict(record), matcher=matcher,
            )
            assert first.status == "promoted"
        updated_record = dict(record)
        updated_record["price"] = record["price"] + 1
        with Session(engine) as session, session.begin():
            second = persist_bplatz_record(
                session, store_id=store_id, raw_record=updated_record, matcher=matcher,
            )
            assert second.status == "promoted"
            assert second.offer_id == first.offer_id

        # An unchanged observation is still a new successful hydration. It
        # must append history/audit rows without increasing the Offer count.
        with Session(engine) as session, session.begin():
            third = persist_bplatz_record(
                session, store_id=store_id, raw_record=dict(updated_record), matcher=matcher,
            )
            assert third.status == "promoted"
            assert third.offer_id == first.offer_id

        with Session(engine) as session:
            offers = session.scalars(select(Offer)).all()
            history = session.scalars(
                select(PriceHistory).where(PriceHistory.offer_id == first.offer_id)
            ).all()
            audits = session.scalars(
                select(MatchAudit).where(MatchAudit.offer_id == first.offer_id)
            ).all()
            assert len(offers) == 1
            assert len(history) == 3
            assert len(audits) == 3
            assert offers[0].price == Decimal(str(updated_record["price"]))
            assert offers[0].ingestion_raw_id == third.ingestion_raw_id
    finally:
        engine.dispose()


def test_bplatz_unmatched_record_remains_pending_without_offer(tmp_path):
    from app.services.bplatz_phase2_adapter import persist_bplatz_record
    from scenthunter_next_engine.next_engine_service import NextEngineService

    engine, db_url, _ = _migrated_database(tmp_path)
    try:
        _seed_real_catalog(db_url)
        matcher = NextEngineService.from_catalog_file(BACKEND / "product_catalog.json")
        unknown = {
            "raw_name": "Completely Unknown Fragrance Product 987654",
            "brand_raw": "Unknown Test Brand",
            "size_ml": 100,
            "price": 29.90,
            "currency": "EUR",
            "product_url": "https://en.bplatz.de/products/unknown-test",
            "availability": "in_stock",
            "sku": "BPLATZ-UNKNOWN-987654",
        }
        with Session(engine) as session, session.begin():
            store_id = _create_bplatz_store(session)
            result = persist_bplatz_record(
                session, store_id=store_id, raw_record=unknown, matcher=matcher,
            )
            assert result.status == "pending"
            assert result.offer_id is None
        with Session(engine) as session:
            raw = session.get(IngestionRaw, result.ingestion_raw_id)
            assert raw is not None and raw.status == "pending"
            assert raw.product_variant_id is None
            assert session.scalars(select(Offer)).all() == []
    finally:
        engine.dispose()


def test_bplatz_phase2_feature_flag_and_store_gate_are_safe(monkeypatch, tmp_path):
    import sqlite3
    import catalog_engine

    phase2_db = tmp_path / "phase2-flag-off.sqlite3"
    sqlite3.connect(phase2_db).close()
    monkeypatch.setenv("BPLATZ_PHASE2_PERSISTENCE", "off")
    monkeypatch.setenv("SCENTHUNTER_CATALOG_DATABASE_URL", "sqlite:///" + str(phase2_db))
    catalog_engine._maybe_persist_bplatz_phase2(
        {"name": "Liquid Brun", "price_num": 29.90}, "https://en.bplatz.de/products/liquid-brun",
    )
    connection = sqlite3.connect(phase2_db)
    try:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall() == []
    finally:
        connection.close()

    eligible = {"price_num": 29.90, "availability": "in_stock"}
    assert catalog_engine._should_persist_bplatz_phase2("bplatz", eligible) is True
    assert catalog_engine._should_persist_bplatz_phase2("bplatz", None) is False
    for store in (
        "deloox", "parfumcity", "parfumzentrum", "perfumemarket",
        "sabina", "orioudh", "easycosmetic", "notino",
    ):
        assert catalog_engine._should_persist_bplatz_phase2(store, eligible) is False


def test_failed_bplatz_hydration_never_invokes_phase2_hook(monkeypatch, tmp_path):
    import catalog_engine

    legacy_db = tmp_path / "legacy-catalog.sqlite3"
    monkeypatch.setattr(catalog_engine, "DB_PATH", legacy_db)
    monkeypatch.setattr(catalog_engine, "_SCHEMA_READY", False)
    monkeypatch.setattr(catalog_engine, "http_get", lambda *args, **kwargs: (503, args[0], b""))
    calls = []
    monkeypatch.setattr(
        catalog_engine, "_maybe_persist_bplatz_phase2",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    result = catalog_engine.refresh_url(
        "bplatz", "https://en.bplatz.de/products/failing-test",
    )
    assert result is None
    assert calls == []


def test_phase2_schema_preflight_skips_without_writing_when_tables_missing(monkeypatch, tmp_path):
    import sqlite3
    import catalog_engine

    phase2_db = tmp_path / "phase2-incomplete.sqlite3"
    connection = sqlite3.connect(phase2_db)
    try:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        connection.execute("INSERT INTO alembic_version(version_num) VALUES ('0002_ingestion_raw')")
        connection.commit()
    finally:
        connection.close()

    monkeypatch.setenv("BPLATZ_PHASE2_PERSISTENCE", "true")
    monkeypatch.setenv("SCENTHUNTER_CATALOG_DATABASE_URL", "sqlite:///" + str(phase2_db))
    catalog_engine._maybe_persist_bplatz_phase2(
        {"name": "Liquid Brun", "price_num": 29.90, "availability": "in_stock"},
        "https://en.bplatz.de/products/liquid-brun",
    )
    connection = sqlite3.connect(phase2_db)
    try:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert tables == {"alembic_version"}
    finally:
        connection.close()


def test_missing_bplatz_store_skips_phase2_without_creating_configuration(monkeypatch, tmp_path):
    import catalog_engine

    engine, db_url, _ = _migrated_database(tmp_path)
    try:
        _seed_real_catalog(db_url)
        # Exercise the hard fail-closed path after explicitly removing Bplatz.
        with Session(engine) as session, session.begin():
            seeded_store = session.scalar(select(Store).where(Store.slug == "bplatz"))
            assert seeded_store is not None
            session.delete(seeded_store)
        monkeypatch.setenv("BPLATZ_PHASE2_PERSISTENCE", "true")
        monkeypatch.setenv("SCENTHUNTER_CATALOG_DATABASE_URL", db_url)
        catalog_engine._maybe_persist_bplatz_phase2(
            {
                "name": "Liquid Brun",
                "brand": "French Avenue",
                "size_ml": 100,
                "price_num": 29.90,
                "currency": "EUR",
                "availability": "in_stock",
                "sku": "BPLATZ-STORE-MISSING-TEST",
            },
            "https://en.bplatz.de/products/liquid-brun",
        )
        with Session(engine) as session:
            assert session.scalars(select(Store)).all() == []
            assert session.scalars(select(IngestionRaw)).all() == []
            assert session.scalars(select(Offer)).all() == []
    finally:
        engine.dispose()


def test_successful_bplatz_refresh_url_wires_into_phase2_after_legacy_hydration(
    monkeypatch, tmp_path, capsys,
):
    import catalog_engine

    parsed, record, _normalized, _group = _real_bplatz_components()
    phase2_engine, phase2_url, _ = _migrated_database(tmp_path)
    try:
        _seed_real_catalog(phase2_url)
        with Session(phase2_engine) as session, session.begin():
            _create_bplatz_store(session)
        item = {
            "name": record["raw_name"],
            "brand": record["brand_raw"],
            "size_ml": record["size_ml"],
            "price_num": record["price"],
            "currency": record["currency"],
            "url": record["product_url"],
            "availability": record["availability"],
            "sku": record["sku"],
            "gtin": record["gtin"],
            "mpn": None,
            "concentration": None,
            "fetched_at": 1800000000.0,
        }
        legacy_db = tmp_path / "legacy-hydration.sqlite3"
        monkeypatch.setattr(catalog_engine, "DB_PATH", legacy_db)
        monkeypatch.setattr(catalog_engine, "_SCHEMA_READY", False)
        monkeypatch.setattr(catalog_engine, "_BPLATZ_PHASE2_MATCHER", None)
        monkeypatch.setattr(
            catalog_engine, "http_get",
            lambda *args, **kwargs: (200, record["product_url"], b"<html><h1>Liquid Brun</h1></html>"),
        )
        monkeypatch.setattr(catalog_engine, "parse_product", lambda *args, **kwargs: dict(item))
        monkeypatch.setenv("BPLATZ_PHASE2_PERSISTENCE", "true")
        monkeypatch.setenv("SCENTHUNTER_CATALOG_DATABASE_URL", phase2_url)

        hydrated = catalog_engine.refresh_url("bplatz", record["product_url"])
        assert hydrated is not None
        assert hydrated["name"] == record["raw_name"]
        # A direct refresh_url call is not evidence of normal queue-worker work.
        assert "hydration_worker bplatz" not in capsys.readouterr().out
        # The opt-in Bplatz path must not initialize or touch the legacy DB.
        assert not legacy_db.exists()

        with Session(phase2_engine) as session:
            offers = session.scalars(select(Offer)).all()
            assert len(offers) == 1
            offer = offers[0]
            assert offer.price == Decimal(str(record["price"]))
            assert offer.url == record["product_url"]
            assert offer.availability == "in_stock"
            raw = session.get(IngestionRaw, offer.ingestion_raw_id)
            assert raw is not None and raw.status == "promoted"
            assert session.scalar(select(PriceHistory).where(
                PriceHistory.offer_id == offer.id
            )) is not None
            assert session.scalar(select(MatchAudit).where(
                MatchAudit.offer_id == offer.id
            )) is not None
    finally:
        phase2_engine.dispose()



def test_normal_bplatz_hydration_worker_logs_only_after_phase2_persistence(
    monkeypatch, capsys,
):
    import catalog_engine

    monkeypatch.setattr(catalog_engine, "_foreground_search_running", lambda: False)
    monkeypatch.setattr(catalog_engine, "_queue_mark_done", lambda task: None)
    def fake_refresh_url(store, url):
        context = catalog_engine._thread_local.hydration_worker_context
        context["phase2_persisted"] = True
        context["offer_id"] = "offer-test-id"
        context["ingestion_raw_id"] = "raw-test-id"
        return {
            "name": "Liquid Brun",
            "sku": "BPLATZ-LIQUID-BRUN-100",
            "price_num": 29.90,
            "availability": "in_stock",
        }

    monkeypatch.setattr(catalog_engine, "refresh_url", fake_refresh_url)

    result = catalog_engine._hydrate_one_task({
        "store": "bplatz",
        "url": "https://en.bplatz.de/products/liquid-brun",
        "attempts": 2,
    })

    output = capsys.readouterr().out
    assert result is True
    assert "hydration_worker bplatz product=BPLATZ-LIQUID-BRUN-100 phase2_persisted=true" in output
    assert "worker=" in output
    assert "timestamp=" in output
    assert "offer_id=" in output
    assert "ingestion_raw_id=" in output
