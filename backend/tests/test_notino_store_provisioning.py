from __future__ import annotations

import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Store
from scripts.seed_notino_store import ensure_notino_store


class NotinoStoreProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Store.__table__.create(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_creates_only_the_active_notino_fr_store(self):
        with Session(self.engine) as session, session.begin():
            result = ensure_notino_store(session)
            store = session.scalar(select(Store).where(Store.slug == "notino-fr"))
            self.assertEqual(result["status"], "created")
            self.assertEqual(store.name, "Notino.fr")
            self.assertEqual(store.domain, "notino.fr")
            self.assertEqual(store.country, "FR")
            self.assertEqual(store.currency, "EUR")
            self.assertEqual(store.status, "active")
            self.assertEqual(session.scalar(select(Store.id).where(Store.slug != "notino-fr")), None)

    def test_existing_active_store_is_idempotent(self):
        with Session(self.engine) as session, session.begin():
            first = ensure_notino_store(session)
            second = ensure_notino_store(session)
            self.assertEqual(second["status"], "already_active")
            self.assertEqual(first["store_id"], second["store_id"])
            self.assertEqual(len(session.scalars(select(Store)).all()), 1)

    def test_inactive_or_quarantined_store_is_never_reactivated(self):
        with Session(self.engine) as session, session.begin():
            session.add(Store(name="Notino.fr", slug="notino-fr", domain="notino.fr",
                              country="FR", currency="EUR", status="quarantined"))
            session.flush()
            with self.assertRaisesRegex(RuntimeError, "refusing automatic reactivation"):
                ensure_notino_store(session)
            store = session.scalar(select(Store).where(Store.slug == "notino-fr"))
            self.assertEqual(store.status, "quarantined")


if __name__ == "__main__":
    unittest.main()
