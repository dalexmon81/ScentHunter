"""Cross-process writer coordination for the legacy SQLite catalog.

Every writable connection opened through this module takes an advisory flock
before its first mutating SQL statement and holds it until COMMIT/ROLLBACK.
Read-only connections do not create or acquire the lock. SQLite remains the
source of truth; this lock serializes cooperating ScentHunter processes that
share the same database file/volume.
"""
from __future__ import annotations

import fcntl
import os
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit


_WRITE_SQL = re.compile(
    r"^\s*(?:"
    r"INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER|REINDEX|VACUUM|"
    r"BEGIN\s+(?:IMMEDIATE|EXCLUSIVE)|"
    r"PRAGMA\s+(?:journal_mode|synchronous|wal_checkpoint|"
    r"locking_mode|foreign_keys|user_version|application_id)"
    r")\b",
    re.IGNORECASE,
)


def _needs_writer_lock(sql):
    """Lock every statement except an explicit, conservative read-only allowlist.

    SQLite has mutating statements beyond the common DML/DDL verbs (for
    example ATTACH, VACUUM INTO and some PRAGMAs). Treat unknown statements
    as writes rather than trying to enumerate every possible mutation.
    WITH is always locked because it can contain data-changing statements.
    """
    if not isinstance(sql, str):
        return False
    statement = sql.lstrip()
    while True:
        if statement.startswith("--"):
            newline = statement.find("\\n")
            if newline < 0:
                return True
            statement = statement[newline + 1 :].lstrip()
            continue
        if statement.startswith("/*"):
            end = statement.find("*/", 2)
            if end < 0:
                return True
            statement = statement[end + 2 :].lstrip()
            continue
        break

    if re.match(r"^WITH\\b", statement, re.IGNORECASE):
        return True
    if re.match(r"^SELECT\\b", statement, re.IGNORECASE):
        return False
    if re.match(r"^EXPLAIN\\s+(?:QUERY\\s+PLAN\\s+)?SELECT\\b", statement, re.IGNORECASE):
        return False
    if re.match(
        r"^PRAGMA\\s+(?:table_info|table_xinfo|index_list|index_info|"
        r"foreign_key_list|foreign_key_check|database_list|compile_options|"
        r"integrity_check|quick_check)\\b",
        statement,
        re.IGNORECASE,
    ):
        return False
    return True

def _database_path(database, uri):
    value = os.fspath(database)
    if uri or value.startswith("file:"):
        parsed = urlsplit(value)
        query = parsed.query.lower()
        if "mode=ro" in query:
            return None
        if parsed.scheme != "file":
            return None
        value = unquote(parsed.path)
    if value == ":memory:" or value.startswith("file::memory:"):
        return None
    return Path(value).expanduser().resolve(strict=False)


class CoordinatedSQLiteCursor(sqlite3.Cursor):
    """Cursor that applies the same cross-process lock as connection methods."""

    def execute(self, sql, parameters=(), /):
        connection = self.connection
        if _needs_writer_lock(sql):
            connection._acquire_writer_lock()
        try:
            result = super().execute(sql, parameters)
            if connection._writer_lock_fd is not None and not connection.in_transaction:
                connection._release_writer_lock()
            return result
        except Exception:
            if connection._writer_lock_fd is not None and not connection.in_transaction:
                connection._release_writer_lock()
            raise

    def executemany(self, sql, seq_of_parameters, /):
        connection = self.connection
        if _needs_writer_lock(sql):
            connection._acquire_writer_lock()
        try:
            result = super().executemany(sql, seq_of_parameters)
            if connection._writer_lock_fd is not None and not connection.in_transaction:
                connection._release_writer_lock()
            return result
        except Exception:
            if connection._writer_lock_fd is not None and not connection.in_transaction:
                connection._release_writer_lock()
            raise


class CoordinatedSQLiteConnection(sqlite3.Connection):
    """SQLite connection that holds a per-database process lock per transaction."""

    def __init__(self, database, *args, **kwargs):
        super().__init__(database, *args, **kwargs)
        uri = bool(kwargs.get("uri", args[6] if len(args) > 6 else False))
        path = _database_path(database, uri)
        self._writer_lock_path = (
            Path(str(path) + ".writer.lock") if path is not None else None
        )
        timeout = kwargs.get("timeout", args[0] if args else 5.0)
        self._writer_lock_timeout = max(0.0, float(timeout))
        self._writer_lock_fd = None

    def cursor(self, factory=None):
        return super().cursor(factory or CoordinatedSQLiteCursor)

    def _acquire_writer_lock(self):
        if self._writer_lock_path is None or self._writer_lock_fd is not None:
            return
        self._writer_lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._writer_lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        deadline = time.monotonic() + self._writer_lock_timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._writer_lock_fd = fd
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise sqlite3.OperationalError(
                        "database is locked (catalog writer coordination lock timed out)"
                    )
                time.sleep(min(0.025, max(0.001, deadline - time.monotonic())))
            except Exception:
                os.close(fd)
                raise

    def _release_writer_lock(self):
        fd, self._writer_lock_fd = self._writer_lock_fd, None
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def execute(self, sql, parameters=(), /):
        if _needs_writer_lock(sql):
            self._acquire_writer_lock()
        try:
            cursor = super().execute(sql, parameters)
            if self._writer_lock_fd is not None and not self.in_transaction:
                self._release_writer_lock()
            return cursor
        except Exception:
            if self._writer_lock_fd is not None and not self.in_transaction:
                self._release_writer_lock()
            raise

    def executemany(self, sql, seq_of_parameters, /):
        if _needs_writer_lock(sql):
            self._acquire_writer_lock()
        try:
            cursor = super().executemany(sql, seq_of_parameters)
            if self._writer_lock_fd is not None and not self.in_transaction:
                self._release_writer_lock()
            return cursor
        except Exception:
            if self._writer_lock_fd is not None and not self.in_transaction:
                self._release_writer_lock()
            raise

    def executescript(self, sql_script, /):
        self._acquire_writer_lock()
        try:
            cursor = super().executescript(sql_script)
            if not self.in_transaction:
                self._release_writer_lock()
            return cursor
        except Exception:
            if not self.in_transaction:
                self._release_writer_lock()
            raise

    def commit(self):
        try:
            return super().commit()
        finally:
            self._release_writer_lock()

    def rollback(self):
        try:
            return super().rollback()
        finally:
            self._release_writer_lock()

    def close(self):
        try:
            return super().close()
        finally:
            self._release_writer_lock()

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self._release_writer_lock()


def connect(
    database,
    timeout=5.0,
    detect_types=0,
    isolation_level="",
    check_same_thread=True,
    cached_statements=128,
    uri=False,
):
    """Drop-in sqlite3.connect replacement for the legacy catalog database."""
    return sqlite3.connect(
        database,
        timeout=timeout,
        detect_types=detect_types,
        isolation_level=isolation_level,
        check_same_thread=check_same_thread,
        factory=CoordinatedSQLiteConnection,
        cached_statements=cached_statements,
        uri=uri,
    )
