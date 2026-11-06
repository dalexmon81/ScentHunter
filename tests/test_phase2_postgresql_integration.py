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
