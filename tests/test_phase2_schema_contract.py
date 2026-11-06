import sys
from pathlib import Path
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import ForeignKey, inspect, text
from sqlalchemy.exc import IntegrityError

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
from app.db import make_engine
from app.models import Base, ProductVariant, Offer, PriceHistory, MatchAudit

def test_phase2_declares_all_core_tables():
    assert set(Base.metadata.tables) == {
        "brands", "fragrances", "product_variants", "stores",
        "offers", "price_history", "match_audit", "ingestion_runs",
        "ingestion_raw", "legacy_product_id_map", "legacy_variant_id_map",
    }

def test_canonical_identity_is_separate_from_retailer_offers():
    assert "canonical_key" in ProductVariant.__table__.columns
    assert "product_variant_id" in Offer.__table__.columns
    assert Offer.__table__.c.product_variant_id.nullable is True
    assert "external_product_id" not in ProductVariant.__table__.columns

def test_variant_attributes_and_fixed_precision_prices():
    for field in ("concentration", "size_ml", "is_tester", "is_refill", "is_gift_set", "gtin"):
        assert field in ProductVariant.__table__.columns
    assert str(Offer.__table__.c.price.type) == "NUMERIC(12, 2)"
    assert str(PriceHistory.__table__.c.price.type) == "NUMERIC(12, 2)"
    assert any(isinstance(fk, ForeignKey) for fk in MatchAudit.__table__.c.offer_id.foreign_keys)

def test_active_offers_require_positive_price():
    constraints = {constraint.name for constraint in Offer.__table__.constraints}
    # Base.metadata applies ck_<table>_<constraint_name> to CheckConstraints.
    assert "ck_offers_active_offer_positive_price" in constraints


def test_required_offer_and_catalog_indexes_exist():
    indexes = {index.name for table in Base.metadata.tables.values() for index in table.indexes}
    assert {
        "ix_product_variants_gtin", "ix_product_variants_size_ml",
        "ix_product_variants_concentration", "ix_offers_status",
        "ix_offers_captured_at", "ix_offers_price",
        "ix_offers_store_external_product", "ix_offers_store_id",
        "ix_offers_product_variant_id", "ix_fragrances_name",
    } <= indexes

def test_sqlite_migration_wal_foreign_keys_and_active_offer_integrity(tmp_path, monkeypatch):
    db_path = tmp_path / "catalog" / "catalog.sqlite3"
    monkeypatch.setenv("SCENTHUNTER_CATALOG_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("SCENTHUNTER_DATABASE_URL", raising=False)
    config = Config(str(BACKEND / "alembic.ini"))
    command.upgrade(config, "head")
    engine = make_engine()
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "wal"
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
        tables = set(inspect(engine).get_table_names())
        assert {
            "brands", "fragrances", "product_variants", "stores",
            "offers", "price_history", "match_audit", "ingestion_runs",
            "ingestion_raw", "legacy_product_id_map", "legacy_variant_id_map",
            "alembic_version",
        } <= tables
        with engine.begin() as connection:
            store_id = "00000000-0000-0000-0000-000000000001"
            connection.execute(text(
                "INSERT INTO stores (id,name,slug,currency,status) VALUES (:id,'Test Store','test-store','EUR','active')"
            ), {"id": store_id})
            with pytest.raises(IntegrityError):
                connection.execute(text(
                    "INSERT INTO offers (id,store_id,url,price,currency,source,status) "
                    "VALUES ('00000000-0000-0000-0000-000000000002',:store,'https://example.test',1.0,'EUR','test','active')"
                ), {"store": store_id})
            with pytest.raises(IntegrityError):
                connection.execute(text(
                    "INSERT INTO offers (id,store_id,url,price,currency,availability,source,status) "
                    "VALUES ('00000000-0000-0000-0000-000000000003',:store,'https://example.test',1.0,'EUR','in_stock','test','active')"
                ), {"store": "00000000-0000-0000-0000-000000000099"})
    finally:
        engine.dispose()

def test_database_url_accepts_postgresql(monkeypatch):
    monkeypatch.setenv("SCENTHUNTER_CATALOG_DATABASE_URL", "postgresql+psycopg://localhost/catalog_test")
    from app.db import database_url, make_engine
    assert database_url().startswith("postgresql+psycopg://")
    engine = make_engine()
    try:
        assert engine.dialect.name == "postgresql"
    finally:
        engine.dispose()


def test_database_url_rejects_unsupported_backend(monkeypatch):
    monkeypatch.setenv("SCENTHUNTER_CATALOG_DATABASE_URL", "mysql+pymysql://localhost/catalog")
    from app.db import database_url
    with pytest.raises(RuntimeError, match="Unsupported catalog database backend"):
        database_url()
