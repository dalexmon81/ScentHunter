"""Bounded recovery for queue rows failed by known, fixed parser-call errors.

Dry-run is the default. Applying changes only returns a small, explicit set of
active product URLs to PENDING; it never performs network requests or starts a
bulk catalog resync.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse

try:
    import catalog_engine as engine
except ImportError:  # imported by tests from repository root
    from backend import catalog_engine as engine


MAX_LIMIT_PER_STORE = 10
ELIGIBLE_ERRORS = {
    "orioudh": "_extract_product() missing 1 required positional argument: 'query'",
    "perfumemarket": "name 'STORE' is not defined",
}
ALLOWED_HOSTS = {
    "orioudh": {"orioudh.com", "www.orioudh.com"},
    "perfumemarket": {"perfumemarket.nl", "www.perfumemarket.nl"},
}


def _is_safe_product_url(store: str, url: str) -> bool:
    try:
        parsed = urlparse(str(url or ""))
    except Exception:
        return False
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS.get(store, set()):
        return False
    if parsed.query or parsed.fragment:
        return False
    path = parsed.path.rstrip("/")
    if store == "orioudh":
        return path.startswith("/products/") and len(path.split("/")) >= 3
    if store == "perfumemarket":
        return path.startswith("/products/") and len(path.split("/")) >= 3
    return False


def _current_parser_available(store: str) -> bool:
    try:
        module = importlib.import_module(f"scrapers.{store}.scraper")
        return callable(getattr(module, "extract_product_page", None))
    except Exception:
        return False


def build_recovery_plan(conn, *, now: float | None = None, limit_per_store: int = 10):
    """Return at most ten exact-match historical parser failures per store."""
    now = time.time() if now is None else float(now)
    limit = max(1, min(int(limit_per_store), MAX_LIMIT_PER_STORE))
    plan = []
    for store, signature in ELIGIBLE_ERRORS.items():
        if not _current_parser_available(store):
            continue
        rows = conn.execute(
            """SELECT q.store, q.url, q.state, q.attempts, q.last_error
               FROM hydration_queue AS q
               JOIN store_urls AS u
                 ON u.store=q.store AND u.url=q.url AND u.active=1
               WHERE q.store=?
                 AND q.state IN ('ERROR','DEAD')
                 AND instr(q.last_error, ?) > 0
               ORDER BY q.last_finished_at DESC, q.attempts DESC, q.url
               LIMIT ?""",
            (store, signature, limit),
        ).fetchall()
        for row in rows:
            item = dict(row) if hasattr(row, "keys") else {
                "store": row[0], "url": row[1], "state": row[2],
                "attempts": row[3], "last_error": row[4],
            }
            if _is_safe_product_url(store, item.get("url")):
                plan.append({
                    "store": store,
                    "url": item["url"],
                    "previous_state": item["state"],
                    "previous_attempts": item["attempts"],
                    "reason": "known_parser_call_error_fixed_in_current_code",
                    "new_state": "PENDING",
                    "available_at": now,
                })
    return plan


def recover(*, apply: bool = False, limit_per_store: int = MAX_LIMIT_PER_STORE):
    db_path = Path(engine.DB_PATH).resolve()
    if apply:
        conn = sqlite3.connect(str(db_path), timeout=10)
    else:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON" if not apply else "PRAGMA busy_timeout=10000")
        now = time.time()
        plan = build_recovery_plan(conn, now=now, limit_per_store=limit_per_store)
        if apply and plan:
            with conn:
                for item in plan:
                    conn.execute(
                        """UPDATE hydration_queue
                           SET state='PENDING', attempts=0, available_at=?,
                               last_error=NULL, last_http_status=NULL,
                               last_started_at=NULL, last_finished_at=NULL,
                               leased_until=NULL
                           WHERE store=? AND url=? AND state IN ('ERROR','DEAD')
                             AND instr(last_error, ?) > 0""",
                        (
                            now, item["store"], item["url"],
                            ELIGIBLE_ERRORS[item['store']],
                        ),
                    )
        return {
            "status": "RECOVERY_QUEUED" if apply else "DRY_RUN",
            "read_only": not apply,
            "database_mutated": bool(apply and plan),
            "limit_per_store": max(1, min(int(limit_per_store), MAX_LIMIT_PER_STORE)),
            "eligible_product_urls": len(plan),
            "by_store": {
                store: sum(1 for item in plan if item["store"] == store)
                for store in ELIGIBLE_ERRORS
            },
            "items": plan,
        }
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Queue only eligible rows; default is read-only.")
    parser.add_argument("--limit-per-store", type=int, default=MAX_LIMIT_PER_STORE)
    args = parser.parse_args()
    print(json.dumps(recover(apply=args.apply, limit_per_store=args.limit_per_store), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
