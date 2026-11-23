from __future__ import annotations
import os
import unittest
from unittest.mock import patch
from app.connectors.base import ConnectorUnavailable
from app.workers.celery_app import TASK_ROUTES, celery_app, queue_is_configured, require_worker_broker
from app.workers.queueing import enqueue_discovery
from app.workers.runtime import clear_handlers, register_handler
from app.workers.tasks import HandlerNotConfigured, RetryableCatalogTask, _execute

class CatalogWorkerQueueTests(unittest.TestCase):
    def tearDown(self):
        clear_handlers()

    def test_only_implemented_runtime_stages_have_routes(self):
        expected = {
            "app.workers.tasks.discover_store_products": "discovery",
            "app.workers.tasks.fetch_store_offers": "offers",
            "app.workers.tasks.refresh_price_and_stock": "refresh",
        }
        self.assertEqual({name: route["queue"] for name, route in TASK_ROUTES.items()}, expected)
        self.assertEqual({queue.name for queue in celery_app.conf.task_queues}, {"discovery", "offers", "refresh"})

    def test_unimplemented_pipeline_stages_are_not_registerable(self):
        for stage in ("normalize", "match", "validate", "quarantine", "reprocess"):
            with self.subTest(stage=stage), self.assertRaises(ValueError):
                register_handler(stage, lambda payload: None)

    def test_delivery_and_retry_safety_defaults(self):
        self.assertTrue(celery_app.conf.task_acks_late)
        self.assertTrue(celery_app.conf.task_reject_on_worker_lost)
        self.assertEqual(celery_app.conf.worker_prefetch_multiplier, 1)
        self.assertEqual(celery_app.conf.task_default_delivery_mode, "persistent")
        self.assertEqual(celery_app.conf.task_annotations["*"]["max_retries"], 5)

    def test_transient_connector_outage_is_retryable(self):
        self.assertIn(ConnectorUnavailable, RetryableCatalogTask.autoretry_for)
        self.assertIn(TimeoutError, RetryableCatalogTask.autoretry_for)
        self.assertIn(ConnectionError, RetryableCatalogTask.autoretry_for)

    def test_worker_startup_requires_explicit_broker(self):
        with self.assertRaisesRegex(RuntimeError, "SCENTHUNTER_REDIS_URL"):
            require_worker_broker({})
        self.assertEqual(require_worker_broker({"SCENTHUNTER_REDIS_URL": "rediss://redis.example/0"}), "rediss://redis.example/0")

    def test_queue_always_routes_to_postgres(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {"SCENTHUNTER_QUEUE_BACKEND": "postgres"}, clear=True):
            with patch("app.workers.postgres_queue.enqueue", return_value="job-123") as enqueue:
                self.assertEqual(enqueue_discovery("store-1"), "job-123")
                enqueue.assert_called_once_with("discover", {
                    "store_id": "store-1", "cursor": None, "limit": 100
                })

    def test_discovery_page_limit_is_bounded(self):
        with self.assertRaises(ValueError):
            enqueue_discovery("store-1", limit=1001)

    def test_handler_registry_requires_explicit_registration(self):
        with self.assertRaises(HandlerNotConfigured):
            _execute("discover", {"store_id": "store-1"})
        register_handler("discover", lambda payload: {"accepted": payload["store_id"]})
        self.assertEqual(_execute("discover", {"store_id": "store-1"}), {"accepted": "store-1"})

    def test_unknown_stages_are_rejected(self):
        with self.assertRaises(ValueError):
            register_handler("unknown", lambda payload: None)

if __name__ == "__main__":
    unittest.main()
