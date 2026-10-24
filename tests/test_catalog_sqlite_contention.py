"""Regression tests for real SQLite lock contention and retry behavior."""
import sqlite3

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
    attempts = []

    def insert_after_lock():
        attempts.append(True)
        conn = sqlite3.connect(path, timeout=0)
        try:
            with conn:
                conn.execute("INSERT INTO items(value) VALUES (2)")
            return "inserted"
        except sqlite3.OperationalError as exc:
            # Hold a genuine SQLite write lock on the first attempt, then
            # release it so the retry can prove recovery from real contention.
            if len(attempts) == 1 and ("locked" in str(exc).lower() or "busy" in str(exc).lower()):
                blocker.commit()
                blocker.close()
            raise
        finally:
            conn.close()

    try:
        result = _retry_sqlite_busy(
            insert_after_lock,
            stage="test_real_sqlite_contention",
            attempts=4,
        )
    finally:
        try:
            blocker.close()
        except Exception:
            pass

    assert result == "inserted"
    assert len(attempts) == 2

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

def test_coverage_child_source_contains_bounded_exception_location_fields():
    # This is a structural regression test: the child serializer must preserve
    # a bounded exception type/message/location for diagnostic queue reports.
    import inspect
    from backend.catalog_engine import _coverage_scraper_process

    source = inspect.getsource(_coverage_scraper_process)
    assert "traceback.extract_tb" in source
    assert "stderr=subprocess.PIPE" in source
    assert "location" in source
    assert "stderr=" in source
