"""Concurrency regression tests for the legacy catalog writer lock."""
import multiprocessing
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from catalog_writer_lock import connect, _needs_writer_lock


def _write_transaction(database, started, finished):
    conn = connect(database, timeout=3.0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO writes(value) VALUES (?)", (1,))
        started.put(time.monotonic())
        time.sleep(0.20)
        conn.commit()
    finally:
        conn.close()
        finished.put(time.monotonic())


class CatalogWriterLockTests(unittest.TestCase):
    def test_serializes_writers_in_separate_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "catalog.sqlite3")
            setup = sqlite3.connect(database)
            setup.execute("CREATE TABLE writes(value INTEGER NOT NULL)")
            setup.commit()
            setup.close()

            context = multiprocessing.get_context("spawn")
            started = context.Queue()
            finished = context.Queue()
            processes = [
                context.Process(
                    target=_write_transaction,
                    args=(database, started, finished),
                )
                for _ in range(2)
            ]

            began = time.monotonic()
            for process in processes:
                process.start()
            for process in processes:
                process.join(8)
                self.assertEqual(process.exitcode, 0)

            elapsed = time.monotonic() - began
            start_times = sorted([started.get(timeout=1), started.get(timeout=1)])
            finish_times = [finished.get(timeout=1), finished.get(timeout=1)]

            # The second transaction cannot begin until the first has committed.
            self.assertGreaterEqual(start_times[1] - start_times[0], 0.15)
            self.assertGreaterEqual(elapsed, 0.35)

            check = sqlite3.connect(database)
            try:
                self.assertEqual(
                    check.execute("SELECT COUNT(*) FROM writes").fetchone()[0], 2
                )
            finally:
                check.close()

    def test_cursor_writes_hold_lock_until_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "catalog.sqlite3")
            setup = sqlite3.connect(database)
            setup.execute("CREATE TABLE writes(value INTEGER NOT NULL)")
            setup.commit()
            setup.close()

            first = connect(database, timeout=0.2)
            second = connect(database, timeout=0.05)
            try:
                first.execute("BEGIN IMMEDIATE")
                first.cursor().execute("INSERT INTO writes(value) VALUES (1)")
                with self.assertRaises(sqlite3.OperationalError):
                    second.cursor().execute("INSERT INTO writes(value) VALUES (2)")
                first.commit()
                second.cursor().execute("INSERT INTO writes(value) VALUES (3)")
            finally:
                first.close()
                second.close()

            check = sqlite3.connect(database)
            try:
                self.assertEqual(
                    check.execute("SELECT value FROM writes ORDER BY value").fetchall(),
                    [(1,), (3,)],
                )
            finally:
                check.close()

    def test_lock_detection_covers_comments_and_with_statements(self):
        self.assertTrue(_needs_writer_lock("  -- comment\nUPDATE writes SET value=2"))
        self.assertTrue(_needs_writer_lock("/* comment */ DELETE FROM writes"))
        self.assertTrue(_needs_writer_lock("WITH changed AS (SELECT 1) UPDATE writes SET value=2"))
        self.assertFalse(_needs_writer_lock("SELECT * FROM writes"))

    def test_rollback_releases_lock_for_next_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "catalog.sqlite3")
            setup = sqlite3.connect(database)
            setup.execute("CREATE TABLE writes(value INTEGER NOT NULL)")
            setup.commit()
            setup.close()

            first = connect(database, timeout=1.0)
            first.execute("BEGIN IMMEDIATE")
            first.execute("INSERT INTO writes(value) VALUES (1)")
            first.rollback()
            first.close()

            second = connect(database, timeout=1.0)
            try:
                second.execute("BEGIN IMMEDIATE")
                second.execute("INSERT INTO writes(value) VALUES (2)")
                second.commit()
            finally:
                second.close()

            check = sqlite3.connect(database)
            try:
                self.assertEqual(
                    check.execute("SELECT value FROM writes").fetchall(), [(2,)]
                )
            finally:
                check.close()


if __name__ == "__main__":
    unittest.main()
