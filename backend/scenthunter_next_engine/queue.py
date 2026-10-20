"""Durable SQLite task queue for discovery/hydration work.

Search requests never call this queue. Workers claim leased tasks explicitly;
terminal failures can only be replayed through an audited requeue method.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import sqlite3
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from .errors import ErrorKind, is_retryable

SCHEMA = """
CREATE TABLE IF NOT EXISTS engine_tasks (
  task_id TEXT PRIMARY KEY,
  task_type TEXT NOT NULL CHECK(task_type IN ('discovery','hydration')),
  store TEXT NOT NULL,
  url TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending','processing','done','error','dead')),
  attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
  max_attempts INTEGER NOT NULL DEFAULT 8 CHECK(max_attempts >= 1),
  next_attempt_at REAL NOT NULL,
  lease_until REAL,
  lease_owner TEXT,
  last_error_kind TEXT,
  last_error TEXT,
  replay_reason TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE(task_type, store, url)
);
CREATE INDEX IF NOT EXISTS idx_engine_tasks_due
  ON engine_tasks(status, next_attempt_at, created_at);
CREATE INDEX IF NOT EXISTS idx_engine_tasks_lease
  ON engine_tasks(status, lease_until);
"""

@dataclass(frozen=True)
class QueueTask:
    task_id: str
    task_type: str
    store: str
    url: str
    status: str
    attempts: int
    max_attempts: int
    lease_until: float | None
    lease_owner: str | None
    last_error_kind: str | None = None
    last_error: str | None = None


class DurableTaskQueue:
    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5000,
                 base_backoff_seconds: float = 15.0, max_backoff_seconds: float = 3600.0):
        self.path = str(path)
        legacy_path = str(os.environ.get("SCENTHUNTER_LEGACY_DB") or os.environ.get("SCENTHUNTER_CATALOG_DB", "")).strip()
        if self.path != ":memory:" and legacy_path and Path(self.path).expanduser().resolve() == Path(legacy_path).expanduser().resolve():
            raise RuntimeError("next-engine queue must not use the legacy catalog database")
        self._memory_uri = None
        self._memory_anchor = None
        self.busy_timeout_ms = int(busy_timeout_ms)
        self.base_backoff_seconds = float(base_backoff_seconds)
        self.max_backoff_seconds = float(max_backoff_seconds)
        if self.busy_timeout_ms < 0 or self.base_backoff_seconds <= 0 or self.max_backoff_seconds < self.base_backoff_seconds:
            raise ValueError("invalid queue timeout/backoff configuration")
        if self.path == ":memory:":
            self._memory_uri = f"file:scenthunter_queue_{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._memory_anchor = sqlite3.connect(self._memory_uri, uri=True, timeout=self.busy_timeout_ms / 1000)
        else:
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self):
        target = self._memory_uri or self.path
        conn = sqlite3.connect(target, uri=bool(self._memory_uri), timeout=self.busy_timeout_ms / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        return conn

    def initialize(self):
        with self.connect() as conn:
            if not self._memory_uri:
                conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    @staticmethod
    def _validate_url(url: str) -> str:
        value = str(url or "").strip()
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("task URL must be an absolute HTTP(S) URL without credentials")
        return value

    def enqueue(self, *, task_type: str, store: str, url: str,
                max_attempts: int = 8, now: float | None = None,
                reopen_done: bool = False) -> tuple[str, bool]:
        kind = str(task_type or "").strip().lower()
        store_key = str(store or "").strip().casefold()
        target = self._validate_url(url)
        if kind not in {"discovery", "hydration"}:
            raise ValueError("task_type must be discovery or hydration")
        if not store_key:
            raise ValueError("store is required")
        if isinstance(max_attempts, bool) or int(max_attempts) < 1:
            raise ValueError("max_attempts must be positive")
        stamp = time.time() if now is None else float(now)
        task_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT task_id FROM engine_tasks WHERE task_type=? AND store=? AND url=?",
                (kind, store_key, target),
            ).fetchone()
            if row:
                existing = conn.execute("SELECT status FROM engine_tasks WHERE task_id=?", (row["task_id"],)).fetchone()
                if reopen_done and existing and existing["status"] == "done":
                    conn.execute(
                        """UPDATE engine_tasks SET status='pending',attempts=0,max_attempts=?,
                           next_attempt_at=?,lease_until=NULL,lease_owner=NULL,last_error_kind=NULL,
                           last_error=NULL,replay_reason='scheduled refresh',updated_at=? WHERE task_id=?""",
                        (int(max_attempts), stamp, stamp, row["task_id"]),
                    )
                    conn.commit()
                    return str(row["task_id"]), True
                conn.commit()
                return str(row["task_id"]), False
            conn.execute(
                """INSERT INTO engine_tasks(task_id,task_type,store,url,status,attempts,max_attempts,
                   next_attempt_at,created_at,updated_at) VALUES(?,?,?,?, 'pending',0,?,?,?,?)""",
                (task_id, kind, store_key, target, int(max_attempts), stamp, stamp, stamp),
            )
            conn.commit()
        return task_id, True

    def _recover_expired(self, conn, now: float) -> None:
        conn.execute(
            """UPDATE engine_tasks SET status=CASE WHEN attempts>=max_attempts THEN 'dead' ELSE 'pending' END,
               lease_until=NULL,lease_owner=NULL,updated_at=?
               WHERE status='processing' AND lease_until IS NOT NULL AND lease_until<=?""",
            (now, now),
        )

    def claim(self, *, worker_id: str, lease_seconds: float = 60.0,
              now: float | None = None) -> QueueTask | None:
        owner = str(worker_id or "").strip()
        if not owner:
            raise ValueError("worker_id is required")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        stamp = time.time() if now is None else float(now)
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._recover_expired(conn, stamp)
            row = conn.execute(
                """SELECT * FROM engine_tasks WHERE status='pending' AND next_attempt_at<=?
                   AND attempts<max_attempts ORDER BY next_attempt_at,created_at LIMIT 1""",
                (stamp,),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            lease_until = stamp + float(lease_seconds)
            conn.execute(
                """UPDATE engine_tasks SET status='processing',attempts=attempts+1,
                   lease_until=?,lease_owner=?,updated_at=? WHERE task_id=? AND status='pending'""",
                (lease_until, owner, stamp, row["task_id"]),
            )
            updated = conn.execute("SELECT * FROM engine_tasks WHERE task_id=?", (row["task_id"],)).fetchone()
            conn.commit()
            return self._task(updated)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _task(row) -> QueueTask:
        return QueueTask(
            task_id=str(row["task_id"]), task_type=str(row["task_type"]),
            store=str(row["store"]), url=str(row["url"]), status=str(row["status"]),
            attempts=int(row["attempts"]), max_attempts=int(row["max_attempts"]),
            lease_until=float(row["lease_until"]) if row["lease_until"] is not None else None,
            lease_owner=row["lease_owner"], last_error_kind=row["last_error_kind"],
            last_error=row["last_error"],
        )

    def complete(self, task_id: str, *, worker_id: str, now: float | None = None) -> bool:
        stamp = time.time() if now is None else float(now)
        with self.connect() as conn:
            cursor = conn.execute(
                """UPDATE engine_tasks SET status='done',lease_until=NULL,lease_owner=NULL,updated_at=?
                   WHERE task_id=? AND status='processing' AND lease_owner=?""",
                (stamp, task_id, worker_id),
            )
            return cursor.rowcount == 1

    def fail(self, task_id: str, *, worker_id: str, error_kind: ErrorKind | str,
             message: str, retry_after_seconds: float | None = None,
             now: float | None = None) -> str:
        stamp = time.time() if now is None else float(now)
        kind = error_kind if isinstance(error_kind, ErrorKind) else ErrorKind(str(error_kind))
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM engine_tasks WHERE task_id=? AND status='processing' AND lease_owner=?",
                (task_id, worker_id),
            ).fetchone()
            if row is None:
                conn.rollback()
                raise ValueError("task is not leased by this worker")
            attempts = int(row["attempts"])
            retryable = is_retryable(kind)
            if retry_after_seconds is not None:
                retryable = retryable or kind == ErrorKind.RATE_LIMITED
            if not retryable or attempts >= int(row["max_attempts"]):
                status = "dead" if not retryable or attempts >= int(row["max_attempts"]) else "error"
                conn.execute(
                    """UPDATE engine_tasks SET status=?,lease_until=NULL,lease_owner=NULL,
                       last_error_kind=?,last_error=?,updated_at=? WHERE task_id=?""",
                    (status, kind.value, str(message)[:2000], stamp, task_id),
                )
                conn.commit()
                return status
            exponent = min(max(attempts - 1, 0), 16)
            base = min(self.max_backoff_seconds, self.base_backoff_seconds * (2 ** exponent))
            digest = int(hashlib.sha256(task_id.encode()).hexdigest()[:8], 16)
            jitter_factor = 0.85 + (digest % 301) / 1000.0
            delay = min(self.max_backoff_seconds, base * jitter_factor)
            if retry_after_seconds is not None and kind == ErrorKind.RATE_LIMITED:
                delay = min(self.max_backoff_seconds, max(delay, max(0.0, float(retry_after_seconds))))
            conn.execute(
                """UPDATE engine_tasks SET status='pending',next_attempt_at=?,lease_until=NULL,
                   lease_owner=NULL,last_error_kind=?,last_error=?,updated_at=? WHERE task_id=?""",
                (stamp + delay, kind.value, str(message)[:2000], stamp, task_id),
            )
            conn.commit()
            return "pending"

    def requeue_dead(self, task_id: str, *, reason: str, now: float | None = None) -> bool:
        explanation = str(reason or "").strip()
        if not explanation:
            raise ValueError("replay reason is required")
        stamp = time.time() if now is None else float(now)
        with self.connect() as conn:
            cursor = conn.execute(
                """UPDATE engine_tasks SET status='pending',attempts=0,next_attempt_at=?,
                   lease_until=NULL,lease_owner=NULL,replay_reason=?,updated_at=?
                   WHERE task_id=? AND status='dead'""",
                (stamp, explanation[:1000], stamp, task_id),
            )
            return cursor.rowcount == 1

    def get(self, task_id: str) -> QueueTask | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM engine_tasks WHERE task_id=?", (task_id,)).fetchone()
            return self._task(row) if row else None

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            return {str(row["status"]): int(row["count"]) for row in conn.execute(
                "SELECT status,COUNT(*) AS count FROM engine_tasks GROUP BY status"
            )}
