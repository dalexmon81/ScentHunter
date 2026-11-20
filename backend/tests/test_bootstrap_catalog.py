"""Regression tests for the restart-safe pilot catalog bootstrap."""
from __future__ import annotations

import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Base, Store
from scripts.bootstrap_catalog import ensure_notino_store


class PilotCatalogBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_missing_notino_store_is_created_active(self):
        with Session(self.engine) as session, session.begin():
            result = ensure_notino_store(session)
            store = session.scalar(select(Store).where(Store.slug == "notino-fr"))
            self.assertEqual(result, "created_active")
            self.assertIsNotNone(store)
            self.assertEqual(store.status, "active")
            self.assertEqual(store.domain, "notino.fr")

    def test_existing_quarantined_store_is_never_reactivated(self):
        with Session(self.engine) as session, session.begin():
            session.add(Store(
                name="Notino.fr", slug="notino-fr", domain="notino.fr",
                country="FR", currency="EUR", status="quarantined",
            ))
        with Session(self.engine) as session, session.begin():
            result = ensure_notino_store(session)
            store = session.scalar(select(Store).where(Store.slug == "notino-fr"))
            self.assertEqual(result, "preserved_existing_quarantined")
            self.assertEqual(store.status, "quarantined")

    def test_existing_inactive_store_is_never_reactivated(self):
        with Session(self.engine) as session, session.begin():
            session.add(Store(
                name="Notino.fr", slug="notino-fr", domain="notino.fr",
                country="FR", currency="EUR", status="inactive",
            ))
        with Session(self.engine) as session, session.begin():
            result = ensure_notino_store(session)
            store = session.scalar(select(Store).where(Store.slug == "notino-fr"))
            self.assertEqual(result, "preserved_existing_inactive")
            self.assertEqual(store.status, "inactive")


if __name__ == "__main__":
    unittest.main()
