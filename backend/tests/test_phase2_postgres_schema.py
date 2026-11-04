import os
import unittest
from decimal import Decimal

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.models import Base
from app.models.catalog import Brand, Fragrance, ProductVariant, Store, IngestionRaw, Offer


class PostgreSQLMigrationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.environ.get("SCENTHUNTER_CATALOG_DATABASE_URL", "")
        if not url.startswith(("postgresql://", "postgresql+psycopg://")):
            raise unittest.SkipTest("Disposable PostgreSQL service is not configured")
        cls.engine = create_engine(url, pool_pre_ping=True)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "engine"):
            cls.engine.dispose()

    def test_alembic_head_and_required_schema(self):
        inspector = inspect(self.engine)
        tables = set(inspector.get_table_names())
        self.assertTrue(set(Base.metadata.tables).issubset(tables))
        with self.engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        self.assertEqual(revision, "0009_catalog_search_fts")
        for table in ("fragrances", "product_variants", "offers", "ingestion_raw"):
            self.assertTrue(inspector.get_foreign_keys(table), table)
        indexes = {item["name"] for table in ("brands", "fragrances") for item in inspector.get_indexes(table)}
        self.assertTrue({"ix_brands_name_fts", "ix_fragrances_name_fts"}.issubset(indexes))

    def test_json_uuid_numeric_and_transaction_rollback(self):
        from uuid import uuid4

        brand_id, fragrance_id, variant_id, store_id, raw_id, offer_id = [uuid4() for _ in range(6)]
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    text("INSERT INTO brands (id,name,slug,normalized_name) VALUES (:id,'Test Brand',:slug,:slug)"),
                    {"id": brand_id, "slug": "phase2-" + brand_id.hex},
                )
                connection.execute(
                    text("INSERT INTO fragrances (id,brand_id,name,slug) VALUES (:id,:brand,'Test Fragrance',:slug)"),
                    {"id": fragrance_id, "brand": brand_id, "slug": "test-" + fragrance_id.hex},
                )
                connection.execute(
                    text("INSERT INTO product_variants (id,fragrance_id,canonical_key) VALUES (:id,:fragrance,:key)"),
                    {"id": variant_id, "fragrance": fragrance_id, "key": "phase2-" + variant_id.hex},
                )
                connection.execute(
                    text("INSERT INTO stores (id,name,slug) VALUES (:id,'Test Store',:slug)"),
                    {"id": store_id, "slug": "phase2-" + store_id.hex},
                )
                connection.execute(
                    text("INSERT INTO ingestion_raw (id,store_id,raw_payload) VALUES (:id,:store,CAST(:payload AS json))"),
                    {"id": raw_id, "store": store_id, "payload": '{"source":"ci","count":1}'},
                )
                connection.execute(
                    text("""INSERT INTO offers
                    (id,store_id,product_variant_id,ingestion_raw_id,url,price,currency,source,status,availability)
                    VALUES (:id,:store,:variant,:raw,'https://example.invalid/item',:price,'EUR','ci','active','in_stock')"""),
                    {"id": offer_id, "store": store_id, "variant": variant_id, "raw": raw_id, "price": Decimal("12.34")},
                )
                raise RuntimeError("intentional rollback")
        except RuntimeError as exc:
            self.assertEqual(str(exc), "intentional rollback")

        with self.engine.connect() as connection:
            count = connection.execute(
                text("SELECT count(*) FROM offers WHERE id=:id"), {"id": offer_id}
            ).scalar_one()
            self.assertEqual(count, 0)

    def test_foreign_key_rejects_unknown_store(self):
        from uuid import uuid4
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as connection:
                connection.execute(
                    text("INSERT INTO ingestion_raw (id,store_id,raw_payload) VALUES (:id,:store,'{}'::json)"),
                    {"id": uuid4(), "store": uuid4()},
                )


if __name__ == "__main__":
    unittest.main()
