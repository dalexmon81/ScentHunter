"""Plan and optionally recover historical Deloox parser failures.

Default mode is read-only. Applying recovery requires BOTH --apply and
--confirm-recovery. Only active, valid numeric Deloox product URLs whose
store_products row still has product_parser_not_found and whose hydration
queue state is DEAD/ERROR are reset to PENDING. Search/homepage routes, DONE
rows, active leases, and last-known offer rows are never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_DB = "/data/store_catalog.sqlite3"
ALLOWED_HOSTS = {
    "deloox.be", "www.deloox.be", "deloox.com", "www.deloox.com",
    "deloox.nl", "www.deloox.nl", "deloox.lu", "www.deloox.lu",
    "deloox.es", "www.deloox.es",
}
PRODUCT_PATH = re.compile(r"/(?:[a-z]{2}/)?(?:product|produit|producto|prodotto)/\d+(?:/|$)", re.I)

EXPECTED_PARSER_GIT_BLOB_SHA = "a2ad6db13ccf84430c4000a4e3dad041e3860a55"


def parser_runtime_status() -> dict:
    root = Path(__file__).resolve().parents[2]
    candidates = (
        Path("/app/backend/scrapers/deloox/scraper.py"),
        root / "backend" / "scrapers" / "deloox" / "scraper.py",
    )
    parser_path = next((path for path in candidates if path.is_file()), None)
    if parser_path is None:
        return {"available": False, "matches_validated_revision": False,
                "reason": "Deloox parser file not found"}
    data = parser_path.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
    return {
        "available": True,
        "path": str(parser_path),
        "git_blob_sha": blob,
        "expected_git_blob_sha": EXPECTED_PARSER_GIT_BLOB_SHA,
        "matches_validated_revision": blob == EXPECTED_PARSER_GIT_BLOB_SHA,
    }



def is_product_url(url: str) -> bool:
    try:
        parsed = urlparse(str(url or "").strip())
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    if (parsed.hostname or "").lower().rstrip(".") not in ALLOWED_HOSTS:
        return False
    return bool(PRODUCT_PATH.search(parsed.path or "/"))


def _connect(db_path: str, readonly: bool) -> sqlite3.Connection:
    path = Path(db_path).resolve()
    if readonly:
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        conn.execute("PRAGMA query_only=ON")
    else:
        conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _candidates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    required = {
        "store_products": {"store", "url", "fetch_status"},
        "store_urls": {"store", "url", "active"},
        "hydration_queue": {
            "store", "url", "state", "attempts", "available_at", "last_error",
            "last_http_status", "last_started_at", "last_finished_at",
            "leased_until", "lease_token",
        },
    }
    for table, expected in required.items():
        actual = {r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')}
        if not expected <= actual:
            raise RuntimeError(f"schema mismatch for {table}: missing {sorted(expected - actual)}")

    rows = conn.execute(
        """
        SELECT DISTINCT p.url, q.state AS queue_state
        FROM store_products AS p
        JOIN store_urls AS u
          ON lower(u.store)=lower(p.store) AND u.url=p.url
        JOIN hydration_queue AS q
          ON lower(q.store)=lower(p.store) AND q.url=p.url
        WHERE lower(p.store)='deloox'
          AND lower(u.store)='deloox' AND u.active=1
          AND lower(q.store)='deloox'
          AND p.fetch_status LIKE '%product_parser_not_found%'
          AND q.state IN ('DEAD','ERROR')
        ORDER BY p.url
        """
    ).fetchall()
    return rows


def build_report(db_path: str = DEFAULT_DB) -> dict:
    conn = _connect(db_path, readonly=True)
    try:
        rows = _candidates(conn)
        runtime = parser_runtime_status()
        eligible = [dict(row) for row in rows if is_product_url(row["url"])]
        excluded = [dict(row) for row in rows if not is_product_url(row["url"])]
        return {
            "status": "REVIEW_REQUIRED",
            "mode": "dry_run",
            "database_path": str(Path(db_path)),
            "read_only": True,
            "database_mutated": False,
            "parser_runtime": runtime,
            "recovery_apply_allowed": runtime["matches_validated_revision"],
            "eligible_product_urls": len(eligible),
            "excluded_non_product_urls": len(excluded),
            "eligible_sample": eligible[:20],
            "excluded_sample": excluded[:20],
            "policy": {
                "only_active_numeric_deloox_product_routes": True,
                "only_parser_not_found_rows": True,
                "only_dead_or_error_queue_rows": True,
                "done_rows_reset": False,
                "active_leases_reset": False,
                "store_products_modified": False,
                "store_urls_modified": False,
            },
        }
    finally:
        conn.close()


def apply_recovery(db_path: str = DEFAULT_DB) -> dict:
    runtime = parser_runtime_status()
    if not runtime["matches_validated_revision"]:
        raise RuntimeError(
            "Recovery blocked: deployed Deloox parser does not match the live-probed revision. "
            "Deploy and verify the parser first; no queue rows were changed. "
            + json.dumps(runtime, sort_keys=True)
        )
    conn = _connect(db_path, readonly=False)
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = _candidates(conn)
        eligible = [row["url"] for row in rows if is_product_url(row["url"])]
        now = time.time()
        changed = 0
        # Candidate eligibility was fully checked inside this BEGIN IMMEDIATE
        # transaction. Stage the validated URLs and reset the queue in one SQL
        # statement instead of thousands of per-URL scans/updates.
        conn.execute(
            "CREATE TEMP TABLE recovery_candidate_urls (url TEXT PRIMARY KEY)"
        )
        conn.executemany(
            "INSERT OR IGNORE INTO recovery_candidate_urls(url) VALUES (?)",
            ((url,) for url in eligible),
        )
        cursor = conn.execute(
            """
            UPDATE hydration_queue
            SET state='PENDING', attempts=0, available_at=?,
                last_error=NULL, last_http_status=NULL,
                last_started_at=NULL, last_finished_at=NULL,
                leased_until=NULL, lease_token=NULL
            WHERE lower(store)='deloox'
              AND state IN ('DEAD','ERROR')
              AND url IN (SELECT url FROM recovery_candidate_urls)
            """,
            (now,),
        )
        changed = cursor.rowcount
        conn.commit()
        return {
            "status": "RECOVERY_QUEUED",
            "mode": "apply",
            "database_path": str(Path(db_path)),
            "read_only": False,
            "database_mutated": changed > 0,
            "eligible_product_urls": len(eligible),
            "queue_rows_reset_to_pending": changed,
            "parser_runtime": runtime,
            "store_products_modified": False,
            "store_urls_modified": False,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true", help="Reset eligible queue rows to PENDING.")
    parser.add_argument(
        "--confirm-recovery", action="store_true",
        help="Required together with --apply; explicitly authorizes queue mutation.",
    )
    args = parser.parse_args()
    if args.apply != args.confirm_recovery:
        parser.error("--apply and --confirm-recovery must be supplied together")
    report = apply_recovery(args.db_path) if args.apply else build_report(args.db_path)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
