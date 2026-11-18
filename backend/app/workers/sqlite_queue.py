"""Durable single-machine SQLite queue for the isolated Fly pilot.

Queue state lives in its own file on the existing persistent volume so queue
writes do not contend with the canonical catalog's SQLite writer.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

DEFAULT_DB = "/data/catalog/ingestion_queue.sqlite3"
MAX_ATTEMPTS = 5
STALE_AFTER_SECONDS = 900


def database_path() -> Path:
    return Path(os.environ.get("SCENTHUNTER_SQLITE_QUEUE_DB", DEFAULT_DB)).expanduser().resolve()


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def ensure_schema() -> None:
    with connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS ingestion_queue_jobs (
            id TEXT PRIMARY KEY,
            stage TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed')),
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at REAL NOT NULL,
            created_at REAL NOT NULL,
            started_at REAL,
            finished_at REAL,
            worker_id TEXT,
            last_error TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_ingestion_queue_ready
            ON ingestion_queue_jobs(status, available_at, created_at);
        CREATE INDEX IF NOT EXISTS ix_ingestion_queue_stale
            ON ingestion_queue_jobs(status, started_at);
        CREATE TABLE IF NOT EXISTS ingestion_queue_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)


def _dedupe_key(stage: str, payload: Mapping[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return f"{stage}:{digest}"


def enqueue(stage: str, payload: Mapping[str, Any]) -> str:
    if not stage or not isinstance(payload, Mapping):
        raise ValueError("stage and JSON-object payload are required")
    ensure_schema()
    now = time.time()
    job_id = uuid.uuid4().hex
    dedupe = _dedupe_key(stage, payload)
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            """SELECT id FROM ingestion_queue_jobs
               WHERE stage=? AND status IN ('queued','running')
                 AND json_extract(payload_json, '$') = json_extract(?, '$')
               ORDER BY created_at LIMIT 1""",
            (stage, json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))),
        ).fetchone()
        if existing:
            conn.commit()
            return str(existing["id"])
        conn.execute(
            """INSERT INTO ingestion_queue_jobs
               (id,stage,payload_json,status,attempts,available_at,created_at)
               VALUES(?,?,?,'queued',0,?,?)""",
            (job_id, stage, json.dumps(dict(payload), ensure_ascii=False, sort_keys=True), now, now),
        )
        conn.commit()
    return job_id


def enqueue_daily_once(schedule_key: str, stage: str, payload: Mapping[str, Any], day: str) -> str | None:
    """Atomically enqueue one scheduled job per UTC day."""
    ensure_schema()
    now = time.time()
    job_id = uuid.uuid4().hex
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT value FROM ingestion_queue_meta WHERE key=?", (schedule_key,)
        ).fetchone()
        if row and row["value"] == day:
            conn.commit()
            return None
        conn.execute(
            """INSERT INTO ingestion_queue_jobs
               (id,stage,payload_json,status,attempts,available_at,created_at)
               VALUES(?,?,?,'queued',0,?,?)""",
            (job_id, stage, json.dumps(dict(payload), ensure_ascii=False, sort_keys=True), now, now),
        )
        conn.execute(
            """INSERT INTO ingestion_queue_meta(key,value) VALUES(?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (schedule_key, day),
        )
        conn.commit()
    return job_id


def claim_next(worker_id: str) -> dict[str, Any] | None:
    ensure_schema()
    now = time.time()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT * FROM ingestion_queue_jobs
               WHERE status='queued' AND available_at<=?
               ORDER BY created_at,id LIMIT 1""",
            (now,),
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        cur = conn.execute(
            """UPDATE ingestion_queue_jobs
               SET status='running', attempts=attempts+1, started_at=?, worker_id=?,
                   finished_at=NULL, last_error=NULL
               WHERE id=? AND status='queued'""",
            (now, worker_id, row["id"]),
        )
        conn.commit()
        if cur.rowcount != 1:
            return None
        result = dict(row)
        result.update(status="running", attempts=int(row["attempts"]) + 1, started_at=now, worker_id=worker_id)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result


def finish(job_id: str) -> None:
    with connect() as conn:
        conn.execute(
            """UPDATE ingestion_queue_jobs SET status='completed',finished_at=?
               WHERE id=? AND status='running'""",
            (time.time(), job_id),
        )


def fail_or_retry(job_id: str, attempts: int, error: str) -> str:
    now = time.time()
    if attempts >= MAX_ATTEMPTS:
        status, available = "failed", now
    else:
        status, available = "queued", now + min(900, 2 ** attempts * 15)
    with connect() as conn:
        conn.execute(
            """UPDATE ingestion_queue_jobs
               SET status=?,available_at=?,finished_at=?,last_error=?
               WHERE id=? AND status='running'""",
            (status, available, now if status == "failed" else None, error[:4000], job_id),
        )
    return status


def recover_stale() -> int:
    now = time.time()
    cutoff = now - STALE_AFTER_SECONDS
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            """UPDATE ingestion_queue_jobs
               SET status=CASE WHEN attempts>=? THEN 'failed' ELSE 'queued' END,
                   available_at=?, finished_at=CASE WHEN attempts>=? THEN ? ELSE NULL END,
                   last_error='worker heartbeat expired; job returned to queue',
                   worker_id=NULL
               WHERE status='running' AND started_at<?""",
            (MAX_ATTEMPTS, now, MAX_ATTEMPTS, now, cutoff),
        )
        conn.commit()
        return cur.rowcount
