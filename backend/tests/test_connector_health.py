from __future__ import annotations

import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Store
from app.monitoring.connector_health import (
    record_connector_failure,
    record_connector_success,
    reinstate_connector,
)


class ConnectorHealthTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions() as session, session.begin():
            self.store = Store(
                name="Notino.fr", slug="notino-fr", country="FR",
                currency="EUR", status="active",
            )
            session.add(self.store)
            session.flush()
            self.store_id = self.store.id

    def tearDown(self):
        self.engine.dispose()

    def test_legacy_service_imports_are_same_implementations(self):
        from app.services.connector_health import (
            record_connector_failure as legacy_failure,
            record_connector_success as legacy_success,
            reinstate_connector as legacy_reinstate,
        )
        from app.monitoring.connector_health import (
            record_connector_failure as canonical_failure,
            record_connector_success as canonical_success,
            reinstate_connector as canonical_reinstate,
        )
        self.assertIs(legacy_failure, canonical_failure)
        self.assertIs(legacy_success, canonical_success)
        self.assertIs(legacy_reinstate, canonical_reinstate)

    def test_quarantines_after_five_consecutive_connector_outages(self):
        with self.sessions() as session, session.begin():
            for index in range(4):
                self.assertFalse(record_connector_failure(
                    session, store_id=self.store_id, error=f"timeout-{index}"
                ))
        with self.sessions() as session, session.begin():
            self.assertTrue(record_connector_failure(
                session, store_id=self.store_id, error="feed unavailable"
            ))
        with self.sessions() as session:
            store = session.get(Store, self.store_id)
            self.assertEqual(store.status, "quarantined")
            self.assertEqual(store.consecutive_failures, 5)
            self.assertIsNotNone(store.quarantined_at)
            self.assertEqual(store.last_connector_error, "feed unavailable")

    def test_success_resets_failure_streak_for_active_store(self):
        with self.sessions() as session, session.begin():
            record_connector_failure(session, store_id=self.store_id, error="timeout")
        with self.sessions() as session, session.begin():
            self.assertTrue(record_connector_success(session, store_id=self.store_id))
        with self.sessions() as session:
            store = session.get(Store, self.store_id)
            self.assertEqual(store.consecutive_failures, 0)
            self.assertIsNone(store.last_connector_error)
            self.assertIsNotNone(store.last_successful_sync_at)

    def test_success_does_not_auto_unquarantine(self):
        with self.sessions() as session, session.begin():
            for _ in range(5):
                record_connector_failure(session, store_id=self.store_id, error="timeout")
        with self.sessions() as session, session.begin():
            self.assertFalse(record_connector_success(session, store_id=self.store_id))
        with self.sessions() as session:
            store = session.get(Store, self.store_id)
            self.assertEqual(store.status, "quarantined")
            self.assertEqual(store.consecutive_failures, 5)

    def test_quarantine_requires_explicit_operator_reinstatement(self):
        with self.sessions() as session, session.begin():
            for _ in range(5):
                record_connector_failure(session, store_id=self.store_id, error="feed timeout")
        with self.sessions() as session, session.begin():
            with self.assertRaisesRegex(ValueError, "explicit confirmation"):
                reinstate_connector(session, store_id=self.store_id, confirmed=False)
        with self.sessions() as session, session.begin():
            self.assertTrue(reinstate_connector(
                session, store_id=self.store_id, confirmed=True
            ))
        with self.sessions() as session:
            store = session.get(Store, self.store_id)
            self.assertEqual(store.status, "active")
            self.assertEqual(store.consecutive_failures, 0)
            self.assertIsNone(store.last_connector_error)
            self.assertIsNone(store.quarantined_at)

    def test_invalid_threshold_is_rejected(self):
        with self.sessions() as session, session.begin():
            with self.assertRaises(ValueError):
                record_connector_failure(
                    session, store_id=self.store_id, error="timeout", threshold=0
                )


if __name__ == "__main__":
    unittest.main()
