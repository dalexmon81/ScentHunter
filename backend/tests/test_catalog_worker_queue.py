from __future__ import annotations
import os
import unittest
from unittest.mock import patch
from app.workers.celery_app import TASK_ROUTES, celery_app, queue_is_configured, require_worker_broker
from app.workers.queueing import QueueNotConfigured, enqueue_discovery
from app.workers.runtime import clear_handlers, register_handler
from app.workers.tasks import HandlerNotConfigured, _execute

class CatalogWorkerQueueTests(unittest.TestCase):
    def tearDown(self):
        clear_handlers()
    def test_all_pipeline_stages_have_dedicated_routes(self):
        expected = {
            "discover_store_products": "discovery", "fetch_store_offers": "offers",
            "normalize_offer": "normalization", "match_offer_to_variant": "matching",
            "validate_offer": "validation", "refresh_price_and_stock": "refresh",
            "quarantine_failed_connector": "dead_letter", "reprocess_failed_offers": "dead_letter",
        }
        for task, queue in expected.items():
            self.assertEqual(TASK_ROUTES[f"app.workers.tasks.{task}"]["queue"], queue)
    def test_delivery_and_retry_safety_defaults(self):
        self.assertTrue(celery_app.conf.task_acks_late)
        self.assertTrue(celery_app.conf.task_reject_on_worker_lost)
        self.assertEqual(celery_app.conf.worker_prefetch_multiplier, 1)
        self.assertEqual(celery_app.conf.task_default_delivery_mode, "persistent")
        self.assertEqual(celery_app.conf.task_annotations["*"]["max_retries"], 5)
    def test_queue_requires_explicit_redis_url(self):
        self.assertFalse(queue_is_configured({}))
        self.assertFalse(queue_is_configured({"SCENTHUNTER_REDIS_URL": "sqlite:///x"}))
        self.assertFalse(queue_is_configured({"SCENTHUNTER_REDIS_URL": "redis://"}))
        self.assertFalse(queue_is_configured({"SCENTHUNTER_REDIS_URL": "redis://:6379/0"}))
        self.assertTrue(queue_is_configured({"SCENTHUNTER_REDIS_URL": "redis://redis.example:6379/0"}))
        self.assertTrue(queue_is_configured({"SCENTHUNTER_REDIS_URL": "rediss://redis.example/0"}))
    def test_worker_startup_requires_explicit_broker(self):
        with self.assertRaisesRegex(RuntimeError, "SCENTHUNTER_REDIS_URL"):
            require_worker_broker({})
        self.assertEqual(
            require_worker_broker({"SCENTHUNTER_REDIS_URL": "rediss://redis.example/0"}),
            "rediss://redis.example/0",
        )
    def test_enqueue_fails_closed_without_broker(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(QueueNotConfigured):
                enqueue_discovery("store-1")
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
