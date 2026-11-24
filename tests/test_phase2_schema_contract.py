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
        "brand_aliases", "fragrance_aliases", "product_variant_aliases",
        "product_variant_gtins", "store_products", "discovery_runs", "extraction_runs",
    }

def test_canonical_identity_is_separate_from_retailer_offers():
    assert "canonical_key" in ProductVariant.__table__.columns
    assert "product_variant_id" in Offer.__table__.columns
    assert Offer.__table__.c.product_variant_id.nullable is True
    assert "store_product_id" in Offer.__table__.columns
    assert Offer.__table__.c.store_product_id.nullable is True
    assert "store_product_id" in Base.metadata.tables["ingestion_raw"].columns
    assert "external_product_id" in Base.metadata.tables["store_products"].columns
    assert "ingestion_run_id" in Base.metadata.tables["discovery_runs"].columns
    assert "ingestion_run_id" in Base.metadata.tables["extraction_runs"].columns
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
        "ix_store_products_status_last_seen", "ix_store_products_product_variant_id",
        "ix_brand_aliases_normalized", "ix_fragrance_aliases_normalized",
        "ix_product_variant_aliases_normalized", "ix_product_variant_gtins_normalized",
        "ix_discovery_runs_store_started_at", "ix_extraction_runs_store_started_at",
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
            "brand_aliases", "fragrance_aliases", "product_variant_aliases",
            "product_variant_gtins", "store_products", "discovery_runs", "extraction_runs",
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



def test_phase2_upgrade_backfills_store_products_and_legacy_gtins(tmp_path, monkeypatch):
    import uuid
    import json
    from decimal import Decimal

    db_path = tmp_path / "phase2-backfill" / "catalog.sqlite3"
    monkeypatch.setenv("SCENTHUNTER_CATALOG_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("SCENTHUNTER_DATABASE_URL", raising=False)
    config = Config(str(BACKEND / "alembic.ini"))
    command.upgrade(config, "0006_postgres_ingestion_queue")

    engine = make_engine()
    brand_id, fragrance_id, variant_id, store_id, raw_id, offer_id, history_id = [
        uuid.uuid4() for _ in range(7)
    ]
    ids = {
        "brand": brand_id.hex, "fragrance": fragrance_id.hex,
        "variant": variant_id.hex, "store": store_id.hex,
        "raw": raw_id.hex, "offer": offer_id.hex, "history": history_id.hex,
    }
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO brands (id,name,slug,normalized_name) VALUES (:id,'Dior','dior','dior')"
            ), {"id": ids["brand"]})
            connection.execute(text(
                "INSERT INTO fragrances (id,brand_id,name,slug) VALUES (:id,:brand,'Sauvage','sauvage')"
            ), {"id": ids["fragrance"], "brand": ids["brand"]})
            connection.execute(text(
                "INSERT INTO product_variants (id,fragrance_id,concentration,size_ml,gtin,canonical_key) "
                "VALUES (:id,:fragrance,'Eau de Parfum',100,'4006381333931','dior|sauvage|edp|100')"
            ), {"id": ids["variant"], "fragrance": ids["fragrance"]})
            connection.execute(text(
                "INSERT INTO stores (id,name,slug,currency,status) VALUES (:id,'Notino','notino-fr','EUR','active')"
            ), {"id": ids["store"]})
            payload = json.dumps({
                "product_url": "https://shop.example/sauvage-edp-100",
                "title": "Dior Sauvage Eau de Parfum 100 ml",
            })
            connection.execute(text(
                "INSERT INTO ingestion_raw (id,store_id,raw_payload,external_product_id,product_variant_id,status) "
                "VALUES (:id,:store,:payload,'sku-100',:variant,'promoted')"
            ), {"id": ids["raw"], "store": ids["store"], "payload": payload, "variant": ids["variant"]})
            connection.execute(text(
                "INSERT INTO offers (id,store_id,product_variant_id,external_product_id,ingestion_raw_id,url,price,currency,availability,source,status) "
                "VALUES (:id,:store,:variant,'sku-100',:raw,'https://shop.example/sauvage-edp-100',:price,'EUR','in_stock','ci','active')"
            ), {
                "id": ids["offer"], "store": ids["store"], "variant": ids["variant"],
                "raw": ids["raw"], "price": "89.90",
            })
            connection.execute(text(
                "INSERT INTO price_history (id,offer_id,price,currency,availability) "
                "VALUES (:id,:offer,:price,'EUR','in_stock')"
            ), {"id": ids["history"], "offer": ids["offer"], "price": "89.90"})

        command.upgrade(config, "head")
        with engine.connect() as connection:
            row = connection.execute(text("""
                SELECT sp.id, sp.canonical_url, sp.raw_title, sp.product_variant_id, sp.status,
                       o.store_product_id AS offer_store_product_id,
                       r.store_product_id AS raw_store_product_id,
                       o.price
                FROM store_products sp
                JOIN offers o ON o.store_product_id = sp.id
                JOIN ingestion_raw r ON r.store_product_id = sp.id
                WHERE sp.store_id = :store AND sp.external_product_id = 'sku-100'
            """), {"store": ids["store"]}).mappings().one()
            assert row["canonical_url"] == "https://shop.example/sauvage-edp-100"
            assert row["raw_title"] == "Dior Sauvage Eau de Parfum 100 ml"
            assert row["product_variant_id"] == ids["variant"]
            assert row["status"] == "active"
            assert row["offer_store_product_id"] == row["raw_store_product_id"] == row["id"]
            assert str(row["price"]) in {"89.9", "89.90"}
            gtin = connection.execute(text(
                "SELECT gtin, normalized_gtin, verification_status, source "
                "FROM product_variant_gtins WHERE product_variant_id = :variant"
            ), {"variant": ids["variant"]}).mappings().one()
            assert gtin["gtin"] == "4006381333931"
            assert gtin["normalized_gtin"] == "4006381333931"
            assert gtin["verification_status"] == "legacy"
            assert gtin["source"] == "legacy_product_variants.gtin"
            assert connection.execute(text(
                "SELECT count(*) FROM price_history WHERE id = :id"
            ), {"id": ids["history"]}).scalar_one() == 1
    finally:
        engine.dispose()

def test_database_url_accepts_postgresql_runtime(monkeypatch):
    monkeypatch.setenv("SCENTHUNTER_CATALOG_DATABASE_URL", "postgresql://example.invalid/catalog")
    monkeypatch.delenv("SCENTHUNTER_DATABASE_URL", raising=False)
    from app.db import database_url
    assert database_url() == "postgresql+psycopg://example.invalid/catalog"
