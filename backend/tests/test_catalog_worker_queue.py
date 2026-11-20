from __future__ import annotations
import os
import tempfile
import unittest
from unittest.mock import patch
from app.workers.celery_app import TASK_ROUTES, celery_app, queue_is_configured, require_worker_broker
from app.workers.queueing import QueueNotConfigured, enqueue_discovery
from app.workers.runtime import clear_handlers, register_handler
from app.workers.tasks import HandlerNotConfigured, RetryableCatalogTask, _execute, worker_health_probe
from app.connectors.base import ConnectorUnavailable

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
    def test_worker_health_probe_is_side_effect_free_and_validates_input(self):
        self.assertEqual(worker_health_probe.run("ci-smoke"), {"ok": True, "probe": "ci-smoke"})
        with self.assertRaises(ValueError):
            worker_health_probe.run("")
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
    def test_default_pilot_backend_enqueues_durably_without_redis(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {
                "SCENTHUNTER_QUEUE_BACKEND": "sqlite",
                "SCENTHUNTER_SQLITE_QUEUE_DB": os.path.join(temp, "queue.sqlite3"),
            }, clear=True):
                job_id = enqueue_discovery("store-1")
                self.assertTrue(job_id)
                from app.workers.sqlite_queue import claim_next
                job = claim_next("test-worker")
                self.assertEqual(job["id"], job_id)
                self.assertEqual(job["stage"], "discover")
    def test_redis_backend_fails_closed_without_broker(self):
        with patch.dict(os.environ, {"SCENTHUNTER_QUEUE_BACKEND": "redis"}, clear=True):
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
