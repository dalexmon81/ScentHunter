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
    IngestionRun, StoreAuthorization, StoreShippingRate, IngestionArtifact,
    IngestionDeadLetter, CanonicalIdentityReview,
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
        with cls.source.begin() as connection:
            connection.execute(text(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
            ))
            connection.execute(text(
                "INSERT INTO alembic_version (version_num) VALUES ('0015_user_sessions')"
            ))

        cls.brand_id = uuid.uuid4()
        cls.fragrance_id = uuid.uuid4()
        cls.variant_id = uuid.uuid4()
        cls.store_id = uuid.uuid4()
        cls.raw_id = uuid.uuid4()
        cls.offer_id = uuid.uuid4()
        cls.run_id = uuid.uuid4()
        cls.authorization_id = uuid.uuid4()
        cls.shipping_rate_id = uuid.uuid4()
        cls.artifact_id = uuid.uuid4()
        cls.dead_letter_id = uuid.uuid4()
        cls.review_id = uuid.uuid4()

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
            session.flush()
            session.add(StoreAuthorization(
                id=cls.authorization_id, store_id=cls.store_id,
                status="approved", collection_method="affiliate_feed",
                scopes=["offer_data"], authorization_reference="fixture-consent",
                terms={"fixture": True},
            ))
            session.add(StoreShippingRate(
                id=cls.shipping_rate_id, store_id=cls.store_id,
                country_code="LU", currency="EUR", base_cost=Decimal("4.90"),
                status="estimated", method="official_page",
                source_url="https://example.invalid/shipping",
            ))
            session.add(IngestionArtifact(
                id=cls.artifact_id, store_id=cls.store_id,
                ingestion_run_id=cls.run_id, artifact_format="xml",
                content_type="application/xml", source_url="https://example.invalid/feed.xml",
                sha256="a" * 64, size_bytes=12, raw_data=b"<feed></feed>",
                metadata_json={"fixture": True},
            ))
            session.add(IngestionDeadLetter(
                id=cls.dead_letter_id, task_name="fixture.task",
                task_id="fixture-task-" + cls.dead_letter_id.hex,
                args_repr="[]", kwargs_repr="{}", error="fixture error",
            ))
            session.add(CanonicalIdentityReview(
                id=cls.review_id, fingerprint="b" * 64,
                canonical_key="fixture|product|edp|50|standard",
                normalized_payload={"brand": "Fixture", "fragrance_name": "Product"},
                reason="fixture_review",
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
        self.assertEqual(dry["tables"]["ingestion_artifacts"]["would_insert"], 1)
        self.assertEqual(dry["tables"]["canonical_identity_reviews"]["would_insert"], 1)

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
        self.assertEqual(applied["tables"]["ingestion_artifacts"]["would_insert"], 1)
        for table_report in applied["tables"].values():
            self.assertTrue(table_report["checksums_match_after_import"])
            self.assertEqual(
                table_report["source_sha256"], table_report["target_sha256_after_import"]
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
        with self.target.connect() as connection:
            artifact_raw_data = connection.execute(
                select(IngestionArtifact.raw_data).where(IngestionArtifact.id == self.artifact_id)
            ).scalar_one()
            authorization_reference = connection.execute(
                select(StoreAuthorization.authorization_reference).where(
                    StoreAuthorization.id == self.authorization_id
                )
            ).scalar_one()
            review_reason = connection.execute(
                select(CanonicalIdentityReview.reason).where(
                    CanonicalIdentityReview.id == self.review_id
                )
            ).scalar_one()
        self.assertEqual(artifact_raw_data, b"<feed></feed>")
        self.assertEqual(authorization_reference, "fixture-consent")
        self.assertEqual(review_reason, "fixture_review")


if __name__ == "__main__":
    unittest.main()
