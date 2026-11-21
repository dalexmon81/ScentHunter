from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.workers import sqlite_queue


class SQLiteQueueRetrySafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "queue.sqlite3")
        self.env = patch.dict(
            os.environ, {"SCENTHUNTER_SQLITE_QUEUE_DB": self.path}, clear=True
        )
        self.env.start()
        sqlite_queue.ensure_schema()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def _row(self, job_id):
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                "SELECT * FROM ingestion_queue_jobs WHERE id=?", (job_id,)
            ).fetchone()

    def test_retryable_failure_uses_bounded_backoff(self):
        job_id = sqlite_queue.enqueue("fetch", {"store_id": "s1"})
        job = sqlite_queue.claim_next("worker-1")
        self.assertEqual(job["id"], job_id)

        with patch.object(sqlite_queue.time, "time", return_value=1000.0):
            status = sqlite_queue.fail_or_retry(
                job_id, job["attempts"], "temporary retailer timeout"
            )

        row = self._row(job_id)
        self.assertEqual(status, "queued")
        self.assertEqual(row["status"], "queued")
        self.assertEqual(row["available_at"], 1030.0)
        self.assertIsNone(row["finished_at"])
        self.assertIn("temporary retailer timeout", row["last_error"])

    def test_permanent_failure_does_not_retry(self):
        job_id = sqlite_queue.enqueue("fetch", {"store_id": "s2"})
        job = sqlite_queue.claim_next("worker-1")
        with patch.object(sqlite_queue.time, "time", return_value=2000.0):
            status = sqlite_queue.fail_or_retry(
                job_id, job["attempts"], "invalid retailer payload", retryable=False
            )

        row = self._row(job_id)
        self.assertEqual(status, "failed")
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["finished_at"], 2000.0)

    def test_maximum_attempts_moves_job_to_failed(self):
        job_id = sqlite_queue.enqueue("fetch", {"store_id": "s3"})
        job = sqlite_queue.claim_next("worker-1")
        with patch.object(sqlite_queue.time, "time", return_value=3000.0):
            status = sqlite_queue.fail_or_retry(
                job_id, sqlite_queue.MAX_ATTEMPTS, "retry budget exhausted"
            )

        self.assertEqual(status, "failed")
        self.assertEqual(self._row(job_id)["status"], "failed")

    def test_stale_worker_job_is_requeued_or_failed_at_attempt_limit(self):
        retry_id = sqlite_queue.enqueue("fetch", {"store_id": "s4"})
        failed_id = sqlite_queue.enqueue("fetch", {"store_id": "s5"})
        retry_job = sqlite_queue.claim_next("worker-1")
        failed_job = sqlite_queue.claim_next("worker-1")
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "UPDATE ingestion_queue_jobs SET started_at=?, attempts=? WHERE id=?",
                (1.0, 1, retry_id),
            )
            conn.execute(
                "UPDATE ingestion_queue_jobs SET started_at=?, attempts=? WHERE id=?",
                (1.0, sqlite_queue.MAX_ATTEMPTS, failed_id),
            )

        with patch.object(sqlite_queue.time, "time", return_value=1000.0):
            recovered = sqlite_queue.recover_stale()

        self.assertEqual(recovered, 2)
        self.assertEqual(self._row(retry_id)["status"], "queued")
        self.assertIsNone(self._row(retry_id)["worker_id"])
        self.assertEqual(self._row(failed_id)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
