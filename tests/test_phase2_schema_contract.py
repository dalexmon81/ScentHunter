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
        "canonical_identity_reviews", "ingestion_artifacts", "ingestion_dead_letters",
        "store_authorizations", "store_shipping_rates",
        "user_accounts", "user_delivery_destinations", "user_sessions",
    }

def test_account_and_delivery_destination_are_distinct_schema_entities():
    from app.models import UserAccount, UserDeliveryDestination
    assert "password_hash" in UserAccount.__table__.columns
    assert "password" not in UserAccount.__table__.columns
    assert "residence_country_code" in UserAccount.__table__.columns
    assert "country_code" in UserDeliveryDestination.__table__.columns
    assert "postal_code" in UserDeliveryDestination.__table__.columns


def test_canonical_identity_is_separate_from_retailer_offers():
    assert "canonical_key" in ProductVariant.__table__.columns
    assert "product_variant_id" in Offer.__table__.columns
    assert Offer.__table__.c.product_variant_id.nullable is True
    assert "external_product_id" not in ProductVariant.__table__.columns

def test_variant_attributes_and_fixed_precision_prices():
    for field in ("concentration", "size_ml", "is_tester", "is_refill", "is_gift_set", "is_mini", "gtin"):
        assert field in ProductVariant.__table__.columns
    assert str(Offer.__table__.c.price.type) == "NUMERIC(12, 2)"
    assert str(PriceHistory.__table__.c.price.type) == "NUMERIC(12, 2)"
    assert any(isinstance(fk, ForeignKey) for fk in MatchAudit.__table__.c.offer_id.foreign_keys)

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
    # This test deliberately exercises the supported local SQLite migration path.
    monkeypatch.setenv("SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL", "0")
    config = Config(str(BACKEND / "alembic.ini"))
    command.upgrade(config, "head")
    engine = make_engine()
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "wal"
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
        tables = set(inspect(engine).get_table_names())
        variant_columns = {column["name"] for column in inspect(engine).get_columns("product_variants")}
        assert "is_mini" in variant_columns
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

def test_database_url_normalizes_postgresql_to_psycopg3(monkeypatch):
    monkeypatch.setenv("SCENTHUNTER_CATALOG_DATABASE_URL", "postgresql://example.invalid/catalog")
    from app.db import database_url
    assert database_url() == "postgresql+psycopg://example.invalid/catalog"
