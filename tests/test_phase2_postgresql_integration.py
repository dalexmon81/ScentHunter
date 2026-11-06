from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))


def test_postgresql_migrations_and_offer_promotion():
    database_url = os.environ.get("SCENTHUNTER_CATALOG_DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+")):
        pytest.skip("A disposable PostgreSQL database is required")

    from app.db import make_engine
    from app.models import (
        Brand, Fragrance, ProductVariant, Store, IngestionRaw, Offer,
        PriceHistory, MatchAudit,
    )
    from app.services.ingestion_persistence import (
        stage_raw_offer, record_match, promote_offer,
    )

    config = Config(str(BACKEND / "alembic.ini"))
    command.upgrade(config, "head")
    engine = make_engine()
    try:
        tables = set(inspect(engine).get_table_names())
        required = {
            "brands", "fragrances", "product_variants", "stores", "offers",
            "price_history", "match_audit", "ingestion_runs", "ingestion_raw",
            "legacy_product_id_map", "legacy_variant_id_map", "alembic_version",
        }
        assert required <= tables

        with Session(engine) as session, session.begin():
            brand = Brand(name="CI Test Brand", slug="ci-test-brand",
                          normalized_name="ci test brand")
            session.add(brand)
            session.flush()
            fragrance = Fragrance(brand_id=brand.id, name="CI Test Scent",
                                  slug="ci-test-scent")
            session.add(fragrance)
            session.flush()
            variant = ProductVariant(
                fragrance_id=fragrance.id, concentration="EDP", size_ml=100,
                canonical_key="ci-test-brand|ci-test-scent|edp|100",
            )
            store = Store(name="CI Test Store", slug="ci-test-store",
                          domain="ci.example.test", country="LU",
                          currency="EUR", status="active")
            session.add_all([variant, store])
            session.flush()

            raw_id = stage_raw_offer(
                session, store_id=store.id,
                raw_payload={"fixture": True, "environment": "ci"},
                external_product_id="ci-fixture-001",
            )
            assert record_match(
                session, ingestion_raw_id=raw_id,
                product_variant_id=variant.id, method="exact_gtin",
                confidence=Decimal("0.999"),
            ) == "matched"
            offer_id = promote_offer(
                session, ingestion_raw_id=raw_id,
                price=Decimal("49.90"), currency="EUR",
                url="https://example.test/ci-fixture-001",
                availability="in_stock", source="ci_fixture",
                confidence=Decimal("0.999"),
            )

            offer = session.get(Offer, offer_id)
            assert offer is not None
            assert offer.product_variant_id == variant.id
            assert offer.price == Decimal("49.90")
            assert session.scalar(select(PriceHistory).where(
                PriceHistory.offer_id == offer_id
            )) is not None
            assert session.scalar(select(MatchAudit).where(
                MatchAudit.offer_id == offer_id
            )) is not None
            assert session.get(IngestionRaw, raw_id).status == "promoted"
    finally:
        engine.dispose()


def test_postgresql_catalog_seed_is_idempotent_and_never_imports_offers(tmp_path):
    import json
    import subprocess

    database_url = os.environ.get("SCENTHUNTER_CATALOG_DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+")):
        pytest.skip("A disposable PostgreSQL database is required")

    from app.db import make_engine
    from app.models import Brand, Fragrance, ProductVariant, Offer, LegacyProductIdMap, LegacyVariantIdMap

    # The preceding integration test persists its own offer. Reset only this
    # disposable CI database before asserting the seed never imports offers.
    engine = make_engine()
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "TRUNCATE TABLE ingestion_raw, offers, price_history, match_audit, "
                "ingestion_runs, legacy_variant_id_map, legacy_product_id_map, "
                "product_variants, fragrances, brands, stores RESTART IDENTITY CASCADE"
            )
    finally:
        engine.dispose()

    catalog_path = tmp_path / "catalog-fixture.json"
    catalog_path.write_text(json.dumps({
        "brands": [{"brand_id": "CI-BRAND", "brand_name": "Postgres CI Brand"}],
        "products": [
            {"product_id": "CI-P1", "brand_name": "Postgres CI Brand",
             "canonical_name": "Migration Test Fragrance", "concentration": "EDP"},
            {"product_id": "CI-P2", "brand_name": "Postgres CI Brand",
             "canonical_name": "Identity Without Variant"},
        ],
        "variants": [
            {"variant_id": "CI-V1", "product_id": "CI-P1",
             "concentration": "EDP", "size_ml": 50}
        ],
        "offers": [{"price": 1, "url": "https://must-not-import.example"}],
    }), encoding="utf-8")

    env = os.environ.copy()
    env["SCENTHUNTER_CATALOG_DATABASE_URL"] = database_url
    env.pop("SCENTHUNTER_DATABASE_URL", None)
    command_line = [
        sys.executable, str(BACKEND / "scripts" / "seed_catalog.py"),
        "--catalog", str(catalog_path), "--apply",
    ]
    first = subprocess.run(command_line, cwd=BACKEND.parent, env=env,
                           capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr
    first_report = json.loads(first.stdout)
    assert first_report["status"] == "seeded"
    assert first_report["database_counts"]["offers"] == 0
    assert first_report["invalid_active_offers"] == 0

    second = subprocess.run(command_line, cwd=BACKEND.parent, env=env,
                            capture_output=True, text=True, check=False)
    assert second.returncode == 0, second.stderr
    second_report = json.loads(second.stdout)
    assert second_report["database_counts"]["brands"] == first_report["database_counts"]["brands"]
    assert second_report["database_counts"]["fragrances"] == first_report["database_counts"]["fragrances"]
    assert second_report["database_counts"]["product_variants"] == first_report["database_counts"]["product_variants"]

    engine = make_engine()
    try:
        with Session(engine) as session:
            assert session.scalar(select(Brand).where(Brand.slug == "postgres-ci-brand")) is not None
            assert session.scalar(select(Fragrance).where(Fragrance.slug == "identity-without-variant")) is not None
            assert session.scalar(select(ProductVariant).where(ProductVariant.canonical_key.like("postgres ci brand|migration test fragrance%"))) is not None
            assert session.scalar(select(LegacyProductIdMap).where(LegacyProductIdMap.legacy_product_id == "CI-P2")) is not None
            assert session.scalar(select(LegacyVariantIdMap).where(LegacyVariantIdMap.legacy_variant_id == "CI-V1")) is not None
            assert session.scalar(select(Offer)) is None
    finally:
        engine.dispose()
