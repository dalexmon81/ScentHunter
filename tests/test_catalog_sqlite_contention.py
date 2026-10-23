"""Regression tests for real SQLite lock contention and retry behavior."""
import sqlite3
import threading
import time

from backend.catalog_engine import _retry_sqlite_busy


def test_sqlite_busy_retry_succeeds_after_real_writer_releases_lock(tmp_path):
    path = tmp_path / "contention.sqlite3"
    setup = sqlite3.connect(path)
    setup.execute("CREATE TABLE items (value INTEGER NOT NULL)")
    setup.commit()
    setup.close()

    blocker = sqlite3.connect(path, timeout=0)
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute("INSERT INTO items(value) VALUES (1)")

    released = threading.Event()

    def release_writer():
        time.sleep(0.30)
        blocker.commit()
        blocker.close()
        released.set()

    releaser = threading.Thread(target=release_writer, daemon=True)
    releaser.start()

    def insert_after_lock():
        conn = sqlite3.connect(path, timeout=0)
        try:
            with conn:
                conn.execute("INSERT INTO items(value) VALUES (2)")
            return "inserted"
        finally:
            conn.close()

    try:
        result = _retry_sqlite_busy(
            insert_after_lock,
            stage="test_real_sqlite_contention",
            attempts=4,
        )
        assert result == "inserted"
        assert released.wait(timeout=1)
    finally:
        if not released.is_set():
            blocker.rollback()
            blocker.close()
        releaser.join(timeout=1)

    check = sqlite3.connect(path)
    try:
        values = [row[0] for row in check.execute("SELECT value FROM items ORDER BY value")]
    finally:
        check.close()

    assert values == [1, 2]


def test_sqlite_retry_does_not_swallow_non_lock_operational_errors():
    calls = []

    def fail_with_non_lock_error():
        calls.append(True)
        raise sqlite3.OperationalError("no such table: missing")

    try:
        _retry_sqlite_busy(
            fail_with_non_lock_error,
            stage="test_non_lock_error",
            attempts=4,
        )
    except sqlite3.OperationalError as exc:
        assert "no such table" in str(exc)
    else:
        raise AssertionError("non-lock OperationalError should be propagated")

    assert len(calls) == 1
