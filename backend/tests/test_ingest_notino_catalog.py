from __future__ import annotations

import unittest

from sqlalchemy import Column, MetaData, String, Table, create_engine, select
from sqlalchemy.orm import Session

from app.models import Base, Store
from scripts.ingest_notino_catalog import (
    EXPECTED_REVISION,
    NOTINO_STORE_DOMAIN,
    NOTINO_STORE_SLUG,
    _ensure_notino_store,
)


def make_catalog_engine(revision: str = EXPECTED_REVISION):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    metadata = MetaData()
    version = Table(
        "alembic_version", metadata,
        Column("version_num", String(32), primary_key=True),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(version.insert().values(version_num=revision))
    return engine


class NotinoCatalogIngestionSetupTests(unittest.TestCase):
    def test_store_slug_and_schema_revision_match_current_worker_contract(self):
        self.assertEqual(EXPECTED_REVISION, "0005_connector_quarantine")
        self.assertEqual(NOTINO_STORE_SLUG, "notino-fr")
        self.assertEqual(NOTINO_STORE_DOMAIN, "notino.fr")

    def test_ensure_notino_store_creates_worker_compatible_store(self):
        engine = make_catalog_engine()
        try:
            store_id = _ensure_notino_store(engine)
            with Session(engine) as session:
                store = session.get(Store, store_id)
                self.assertIsNotNone(store)
                self.assertEqual(store.slug, "notino-fr")
                self.assertEqual(store.domain, "notino.fr")
                self.assertEqual(store.status, "active")
                self.assertEqual(session.scalar(select(Store).where(Store.slug == "notino-fr")).id, store_id)
                self.assertEqual(session.scalar(select(Store.id).where(Store.slug == "notino")), None)
        finally:
            engine.dispose()

    def test_ensure_notino_store_is_idempotent(self):
        engine = make_catalog_engine()
        try:
            first = _ensure_notino_store(engine)
            second = _ensure_notino_store(engine)
            self.assertEqual(first, second)
            with Session(engine) as session:
                self.assertEqual(len(session.scalars(select(Store)).all()), 1)
        finally:
            engine.dispose()

    def test_rejects_stale_schema_revision_before_creating_store(self):
        engine = make_catalog_engine("0004_variant_mini")
        try:
            with self.assertRaisesRegex(RuntimeError, "schema_revision_mismatch"):
                _ensure_notino_store(engine)
            with Session(engine) as session:
                self.assertEqual(len(session.scalars(select(Store)).all()), 0)
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
