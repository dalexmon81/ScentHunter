from __future__ import annotations

import os
import unittest
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Offer, Store
from app.workers import sqlite_worker


class PilotRefreshSchedulingTests(unittest.TestCase):
    def test_periodic_refresh_is_due_immediately_after_worker_start(self):
        self.assertTrue(sqlite_worker._schedule_due(1.0, 0.0, 1800))
        self.assertFalse(sqlite_worker._schedule_due(10.0, 1.0, 1800))
        self.assertTrue(sqlite_worker._schedule_due(1801.0, 1.0, 1800))

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions() as session, session.begin():
            notino = Store(
                name="Notino.fr", slug="notino-fr", domain="notino.fr",
                country="FR", currency="EUR", status="active",
            )
            bplatz = Store(
                name="Bplatz", slug="bplatz", domain="bplatz.de",
                country="DE", currency="EUR", status="active",
            )
            session.add_all([notino, bplatz])
            session.flush()
            session.add_all([
                Offer(
                    store_id=notino.id, external_product_id="CJ-100",
                    url="https://www.notino.fr/product/100", price=Decimal("30.00"),
                    currency="EUR", availability="in_stock", source="test",
                    status="active",
                ),
                Offer(
                    store_id=bplatz.id, external_product_id="https://en.bplatz.de/products/101",
                    url="https://en.bplatz.de/products/101", price=Decimal("45.00"),
                    currency="EUR", availability="in_stock", source="test",
                    status="active",
                ),
            ])

    def tearDown(self):
        self.engine.dispose()

    def test_pilot_can_disable_full_notino_daily_discovery(self):
        with patch.dict(os.environ, {
            "SCENTHUNTER_NOTINO_DAILY_DISCOVERY_ENABLED": "0",
        }, clear=True):
            with patch.object(sqlite_worker, "enqueue_daily_once") as enqueue:
                sqlite_worker._schedule_daily_notino_discovery(self.sessions)
        enqueue.assert_not_called()

    def test_enabled_refresh_schedules_existing_notino_and_bplatz_offers(self):
        with patch.dict(os.environ, {
            "SCENTHUNTER_ACTIVE_OFFER_REFRESH_ENABLED": "1",
            "SCENTHUNTER_QUEUE_BACKEND": "sqlite",
        }, clear=True):
            with patch.object(sqlite_worker, "enqueue_offer_refresh") as enqueue:
                sqlite_worker._schedule_active_offer_refresh(self.sessions)
        scheduled = {
            (call.args[0], call.args[1])
            for call in enqueue.call_args_list
        }
        self.assertEqual(
            {external_id for _store_id, external_id in scheduled},
            {"CJ-100", "https://en.bplatz.de/products/101"},
        )
        self.assertEqual(len(scheduled), 2)


if __name__ == "__main__":
    unittest.main()
