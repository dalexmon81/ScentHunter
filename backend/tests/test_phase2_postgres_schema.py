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
        self.assertEqual(revision, "0007_catalog_identity")
        for table in ("fragrances", "product_variants", "offers", "ingestion_raw", "store_products", "brand_aliases", "fragrance_aliases", "product_variant_aliases", "product_variant_gtins", "discovery_runs", "extraction_runs"):
            self.assertTrue(inspector.get_foreign_keys(table), table)

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

    def test_queue_cutover_claim_skips_legacy_backlog_without_mutating_it(self):
        from datetime import datetime, timedelta, timezone
        from uuid import uuid4
        from unittest.mock import patch

        from app.workers import postgres_queue

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=5)
        old_id, new_id = uuid4(), uuid4()
        rows = [
            {
                "id": old_id, "stage": "fetch", "payload": "{}",
                "dedupe": "cutover-old-" + old_id.hex, "available": now - timedelta(hours=1),
                "created": cutoff - timedelta(days=1),
            },
            {
                "id": new_id, "stage": "discover", "payload": '{"store_id":"notino-fr"}',
                "dedupe": "cutover-new-" + new_id.hex, "available": now - timedelta(hours=1),
                "created": now - timedelta(minutes=1),
            },
        ]
        try:
            with self.engine.begin() as connection:
                for row in rows:
                    connection.execute(text("""
                        INSERT INTO ingestion_queue_jobs
                        (id,stage,payload,dedupe_key,status,attempts,max_attempts,available_at,created_at)
                        VALUES (:id,:stage,CAST(:payload AS json),:dedupe,'queued',0,5,:available,:created)
                    """), row)

            with patch.dict(os.environ, {
                "SCENTHUNTER_QUEUE_MIN_CREATED_AT": cutoff.isoformat(),
            }):
                claimed = postgres_queue.claim_next("phase2-cutover-test")
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed["id"], new_id)

            with self.engine.connect() as connection:
                states = dict(connection.execute(text("""
                    SELECT id,status FROM ingestion_queue_jobs
                    WHERE id IN (:old_id,:new_id)
                """), {"old_id": old_id, "new_id": new_id}).all())
            self.assertEqual(states[old_id], "queued")
            self.assertEqual(states[new_id], "running")
        finally:
            with self.engine.begin() as connection:
                connection.execute(text("""
                    DELETE FROM ingestion_queue_jobs WHERE id IN (:old_id,:new_id)
                """), {"old_id": old_id, "new_id": new_id})


if __name__ == "__main__":
    unittest.main()
