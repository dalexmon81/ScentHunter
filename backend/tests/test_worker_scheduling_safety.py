from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from app.workers import sqlite_worker


class WorkerSchedulingSafetyTests(unittest.TestCase):
    def test_all_retailer_schedulers_are_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            session_factory = MagicMock()
            with patch.object(sqlite_worker, "enqueue_daily_once") as enqueue_daily, patch.object(
                sqlite_worker, "enqueue_offer_refresh"
            ) as enqueue_refresh:
                sqlite_worker._schedule_daily_notino_discovery(session_factory)
                sqlite_worker._schedule_daily_legacy_discovery(session_factory)
                sqlite_worker._schedule_active_offer_refresh(session_factory)

            session_factory.assert_not_called()
            enqueue_daily.assert_not_called()
            enqueue_refresh.assert_not_called()

    def test_notino_discovery_requires_explicit_opt_in(self):
        session = MagicMock()
        session.scalar.return_value = "notino-store-id"
        session_context = MagicMock()
        session_context.__enter__.return_value = session
        session_context.__exit__.return_value = False
        session_factory = MagicMock(return_value=session_context)

        with patch.dict(os.environ, {"SCENTHUNTER_NOTINO_DISCOVERY_ENABLED": "1"}, clear=True):
            with patch.object(sqlite_worker, "enqueue_daily_once", return_value="job-1") as enqueue:
                sqlite_worker._schedule_daily_notino_discovery(session_factory)

        session_factory.assert_called_once()
        enqueue.assert_called_once()
        self.assertEqual(enqueue.call_args.args[1], "discover")
        self.assertEqual(enqueue.call_args.args[2]["store_id"], "notino-store-id")

    def test_shopify_retailers_are_not_registered_for_worker_scheduling(self):
        from app.connectors.legacy_scrapers import STORE_SLUGS
        self.assertNotIn("orioudh", STORE_SLUGS)
        self.assertNotIn("parfumcity", STORE_SLUGS)
        self.assertNotIn("orioudh-com", STORE_SLUGS)
        self.assertNotIn("parfumcity-nl", STORE_SLUGS)

    def test_shopify_retailers_fail_closed_in_legacy_dispatcher(self):
        from app.workers.legacy_runtime import _connector_for
        for slug in ("orioudh", "parfumcity", "orioudh-com", "parfumcity-nl"):
            with self.subTest(slug=slug):
                with self.assertRaisesRegex(ValueError, "unsupported legacy store slug"):
                    _connector_for(slug)

    def test_legacy_discovery_requires_global_and_store_query_opt_ins(self):
        session = MagicMock()
        session.execute.return_value.all.return_value = []
        session_context = MagicMock()
        session_context.__enter__.return_value = session
        session_context.__exit__.return_value = False
        session_factory = MagicMock(return_value=session_context)

        with patch.dict(os.environ, {"SCENTHUNTER_LEGACY_DISCOVERY_ENABLED": "1"}, clear=True):
            with patch.object(sqlite_worker, "enqueue_daily_once") as enqueue:
                sqlite_worker._schedule_daily_legacy_discovery(session_factory)

        enqueue.assert_not_called()
        session.execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
