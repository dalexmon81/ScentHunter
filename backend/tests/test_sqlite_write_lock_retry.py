"""Tests for bounded SQLite writer-lock retry."""
import sqlite3
import unittest
from unittest.mock import patch

import catalog_engine


class BeginImmediateRetryTests(unittest.TestCase):
    def test_retries_transient_locked_errors_before_acquiring_writer_slot(self):
        class Connection:
            def __init__(self):
                self.calls = 0

            def execute(self, sql):
                self.calls += 1
                if self.calls < 3:
                    raise sqlite3.OperationalError("database is locked")
                return None

        conn = Connection()
        with patch.object(catalog_engine.time, "sleep") as sleep:
            catalog_engine._begin_immediate_with_retry(conn)

        self.assertEqual(conn.calls, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.1, 0.2])

    def test_does_not_retry_unrelated_operational_errors(self):
        class Connection:
            def execute(self, sql):
                raise sqlite3.OperationalError("disk I/O error")

        with patch.object(catalog_engine.time, "sleep") as sleep:
            with self.assertRaisesRegex(sqlite3.OperationalError, "disk I/O error"):
                catalog_engine._begin_immediate_with_retry(Connection())
        sleep.assert_not_called()

    def test_raises_after_bounded_number_of_lock_attempts(self):
        class Connection:
            def __init__(self):
                self.calls = 0

            def execute(self, sql):
                self.calls += 1
                raise sqlite3.OperationalError("database is locked")

        conn = Connection()
        with patch.object(catalog_engine.time, "sleep"):
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                catalog_engine._begin_immediate_with_retry(conn, attempts=3)
        self.assertEqual(conn.calls, 3)


if __name__ == "__main__":
    unittest.main()
