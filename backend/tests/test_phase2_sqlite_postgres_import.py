import os
import tempfile
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.models import Base
from app.models.catalog import (
    Brand, Fragrance, ProductVariant, Store, LegacyProductIdMap,
    LegacyVariantIdMap, IngestionRaw, Offer, PriceHistory, MatchAudit,
    IngestionRun,
)
from scripts.migrate_canonical_sqlite_to_postgres import inspect_and_import


@unittest.skipUnless(
    os.environ.get("SCENTHUNTER_MIGRATION_TARGET_DATABASE_URL"),
    "requires disposable PostgreSQL migration target",
)
class CanonicalSQLitePostgresImporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.target = create_engine(
            os.environ["SCENTHUNTER_MIGRATION_TARGET_DATABASE_URL"],
            pool_pre_ping=True,
        )
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.source_path = Path(cls.tempdir.name) / "canonical-source.sqlite3"
        cls.source = create_engine(f"sqlite:///{cls.source_path}")
        Base.metadata.create_all(cls.source)

        cls.brand_id = uuid.uuid4()
        cls.fragrance_id = uuid.uuid4()
        cls.variant_id = uuid.uuid4()
        cls.store_id = uuid.uuid4()
        cls.raw_id = uuid.uuid4()
        cls.offer_id = uuid.uuid4()
        cls.run_id = uuid.uuid4()

        with Session(cls.source) as session, session.begin():
            session.add(Brand(
                id=cls.brand_id, name="Importer Test Brand",
                slug="importer-test-brand", normalized_name="importer test brand",
            ))
            session.add(Fragrance(
                id=cls.fragrance_id, brand_id=cls.brand_id,
                name="Importer Test Fragrance", slug="importer-test-fragrance",
            ))
            session.add(ProductVariant(
                id=cls.variant_id, fragrance_id=cls.fragrance_id,
                canonical_key="importer-test|edp|50",
                concentration="EDP", size_ml=50,
            ))
            session.add(Store(
                id=cls.store_id, name="Importer Test Store",
                slug="importer-test-store", domain="example.invalid",
            ))
            session.flush()
            session.add(LegacyProductIdMap(
                legacy_product_id="legacy-importer-product",
                fragrance_id=cls.fragrance_id,
            ))
            session.add(LegacyVariantIdMap(
                legacy_variant_id="legacy-importer-variant",
                product_variant_id=cls.variant_id,
            ))
            session.add(IngestionRaw(
                id=cls.raw_id, store_id=cls.store_id,
                raw_payload={"origin": "isolated-test"},
                product_variant_id=cls.variant_id,
            ))
            session.flush()
            session.add(Offer(
                id=cls.offer_id, ingestion_raw_id=cls.raw_id,
                store_id=cls.store_id, product_variant_id=cls.variant_id,
                url="https://example.invalid/item", price=Decimal("19.95"),
                currency="EUR", availability="in_stock", source="test",
                status="active",
            ))
            session.flush()
            session.add(PriceHistory(
                offer_id=cls.offer_id, price=Decimal("19.95"),
                currency="EUR", availability="in_stock",
            ))
            session.add(MatchAudit(
                offer_id=cls.offer_id, product_variant_id=cls.variant_id,
                method="test_exact", confidence=Decimal("1.000"),
            ))
            session.add(IngestionRun(
                id=cls.run_id, store_id=cls.store_id,
                status="completed", products_discovered=1,
                offers_created=1, offers_updated=0, offers_rejected=0,
                errors=[],
            ))

    @classmethod
    def tearDownClass(cls):
        cls.source.dispose()
        cls.target.dispose()
        cls.tempdir.cleanup()

    def test_dry_run_then_apply_is_idempotent_and_preserves_source(self):
        dry = inspect_and_import(self.source_path, self.target, apply=False)
        self.assertEqual(dry["status"], "dry_run")
        self.assertFalse(dry["source_modified"])
        self.assertFalse(dry["destination_written"])
        self.assertEqual(dry["tables"]["offers"]["would_insert"], 1)

        with self.target.connect() as connection:
            before = connection.execute(
                select(func.count()).select_from(Offer).where(Offer.id == self.offer_id)
            ).scalar_one()
        self.assertEqual(before, 0)

        with self.target.connect() as connection:
            database_name = connection.execute(text("SELECT current_database()")).scalar_one()
        applied = inspect_and_import(
            self.source_path, self.target, apply=True, confirm_target=database_name
        )
        self.assertEqual(applied["status"], "applied")
        self.assertTrue(applied["destination_written"])
        self.assertEqual(applied["tables"]["offers"]["would_insert"], 1)
        for table_report in applied["tables"].values():
            self.assertTrue(table_report["checksums_match_after_import"])
            self.assertEqual(
                table_report["source_sha256"], table_report["target_sha256_after"]
            )

        repeated = inspect_and_import(
            self.source_path, self.target, apply=True, confirm_target=database_name
        )
        self.assertEqual(repeated["tables"]["offers"]["would_insert"], 0)
        self.assertEqual(repeated["tables"]["offers"]["already_present_identical"], 1)

        with self.source.connect() as connection:
            source_offer_count = connection.execute(
                select(func.count()).select_from(Offer).where(Offer.id == self.offer_id)
            ).scalar_one()
        self.assertEqual(source_offer_count, 1)


if __name__ == "__main__":
    unittest.main()
