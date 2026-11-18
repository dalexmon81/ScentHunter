from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from app.workers import sqlite_queue


class SQLiteQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "queue.sqlite3")
        self.env = patch.dict(os.environ, {"SCENTHUNTER_SQLITE_QUEUE_DB": self.path})
        self.env.start()
        sqlite_queue.ensure_schema()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_enqueue_is_durable_and_claimable(self):
        job_id = sqlite_queue.enqueue("fetch", {"store_id": "store-1", "external_product_id": "p-1"})
        claimed = sqlite_queue.claim_next("worker-a")
        self.assertEqual(claimed["id"], job_id)
        self.assertEqual(claimed["status"], "running")
        self.assertEqual(claimed["payload"]["external_product_id"], "p-1")
        sqlite_queue.finish(job_id)
        with sqlite_queue.connect() as conn:
            row = conn.execute("SELECT status FROM ingestion_queue_jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(row["status"], "completed")

    def test_duplicate_active_payload_returns_existing_job(self):
        payload = {"store_id": "store-1", "external_product_id": "p-1"}
        first = sqlite_queue.enqueue("fetch", payload)
        second = sqlite_queue.enqueue("fetch", payload)
        self.assertEqual(first, second)

    def test_completed_payload_can_be_queued_again(self):
        payload = {"store_id": "store-1", "external_product_id": "p-1"}
        first = sqlite_queue.enqueue("fetch", payload)
        sqlite_queue.claim_next("worker-a")
        sqlite_queue.finish(first)
        second = sqlite_queue.enqueue("fetch", payload)
        self.assertNotEqual(first, second)

    def test_failure_retries_then_dead_letters(self):
        job_id = sqlite_queue.enqueue("fetch", {"external_product_id": "p-1"})
        job = sqlite_queue.claim_next("worker-a")
        self.assertEqual(sqlite_queue.fail_or_retry(job_id, job["attempts"], "temporary"), "queued")
        with sqlite_queue.connect() as conn:
            conn.execute("UPDATE ingestion_queue_jobs SET available_at=0 WHERE id=?", (job_id,))
        for attempt in range(2, sqlite_queue.MAX_ATTEMPTS + 1):
            with sqlite_queue.db_connection() as conn:
                conn.execute("UPDATE ingestion_queue_jobs SET available_at=0 WHERE id=?", (job_id,))
            job = sqlite_queue.claim_next("worker-a")
            self.assertEqual(job["attempts"], attempt)
            status = sqlite_queue.fail_or_retry(job_id, job["attempts"], "failure")
        self.assertEqual(status, "failed")

    def test_daily_scheduler_enqueues_only_once_per_day(self):
        payload = {"store_id": "store-1", "cursor": None, "limit": 100}
        first = sqlite_queue.enqueue_daily_once("daily", "discover", payload, "2026-11-18")
        second = sqlite_queue.enqueue_daily_once("daily", "discover", payload, "2026-11-18")
        third = sqlite_queue.enqueue_daily_once("daily", "discover", payload, "2026-11-19")
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertIsNotNone(third)


if __name__ == "__main__":
    unittest.main()
