"""Focused tests for opt-in SQLite transaction telemetry."""

import contextlib
import io
import json
import os
import sqlite3
import unittest
from unittest.mock import patch

from backend.catalog_engine import _TelemetrySQLiteConnection


class SQLiteTransactionTelemetryTests(unittest.TestCase):
    def _events(self, output):
        events = []
        for line in output.getvalue().splitlines():
            if line.startswith("SQLITE_TXN_TELEMETRY "):
                events.append(json.loads(line.split(" ", 1)[1]))
        return events

    def test_cursor_execute_begin_commit_is_correlated_once(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"SCENTHUNTER_SQLITE_TXN_TELEMETRY": "1"}):
            with contextlib.redirect_stdout(output):
                conn = sqlite3.connect(":memory:", factory=_TelemetrySQLiteConnection)
                conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
                conn.commit()
                conn.cursor().execute("INSERT INTO sample DEFAULT VALUES")
                conn.commit()
                conn.close()

        events = self._events(output)
        begins = [event for event in events if event["event"] == "begin"]
        commits = [event for event in events if event["event"] == "commit"]
        self.assertEqual(len(begins), 1)
        self.assertEqual(len(commits), 1)
        self.assertEqual(begins[0]["operation"], "cursor.execute")
        self.assertEqual(begins[0]["connection_id"], commits[0]["connection_id"])
        self.assertGreaterEqual(commits[0]["duration_ms"], 0)
        self.assertTrue(any(frame["function"] == "test_cursor_execute_begin_commit_is_correlated_once"
                            for frame in begins[0]["caller"]))

    def test_context_manager_emits_one_finish_event(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"SCENTHUNTER_SQLITE_TXN_TELEMETRY": "1"}):
            with contextlib.redirect_stdout(output):
                conn = sqlite3.connect(":memory:", factory=_TelemetrySQLiteConnection)
                conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
                conn.commit()
                with conn:
                    conn.execute("INSERT INTO sample DEFAULT VALUES")
                conn.close()

        events = self._events(output)
        self.assertEqual(sum(event["event"] == "begin" for event in events), 1)
        self.assertEqual(sum(event["event"] == "commit" for event in events), 1)
        self.assertFalse(any(event["event"] == "rollback" for event in events))

    def test_telemetry_is_off_by_default(self):
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True):
            with contextlib.redirect_stdout(output):
                conn = sqlite3.connect(":memory:", factory=_TelemetrySQLiteConnection)
                conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
                conn.commit()
                conn.close()
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
