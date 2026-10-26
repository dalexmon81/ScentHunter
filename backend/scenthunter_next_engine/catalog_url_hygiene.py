"""Read-only audit of invalid active Deloox catalog URLs.

Run with:
    python -m backend.scenthunter_next_engine.catalog_url_hygiene

This command reports URLs rejected by the catalog's current product-URL
admission contract. It never writes to the database or changes product data.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Iterable

from backend import catalog_engine


def classify_invalid_urls(rows: Iterable[dict]) -> list[dict]:
    """Return active Deloox URL rows rejected by the current admission contract."""
    invalid = []
    base_url = catalog_engine.STORES["deloox"][0]
    for row in rows:
        if not row.get("active"):
            continue
        if catalog_engine._html_product_url("deloox", row.get("url"), base_url) is None:
            invalid.append({
                "store": row.get("store", "deloox"),
                "url": row.get("url"),
                "slug": row.get("slug"),
                "reason": "rejected_by_current_product_url_admission",
            })
    return invalid


def _local_database_path() -> Path:
    """Resolve the configured catalog DB without creating or initializing it."""
    configured = os.environ.get("SCENTHUNTER_CATALOG_DB")
    if configured:
        return Path(configured).expanduser()
    return Path(catalog_engine.DB_PATH).expanduser()


def audit() -> dict:
    """Inspect active Deloox URL rows with a strictly read-only SQLite connection."""
    db_path = _local_database_path()
    base = {
        "scope": "local_database_only",
        "database_path": str(db_path),
        "read_only": True,
        "database_mutated": False,
    }
    if not db_path.is_file():
        return {
            **base,
            "status": "DATABASE_NOT_FOUND",
            "note": "No local catalog database file exists; this is not a production inventory.",
            "active_deloox_urls_examined": 0,
            "invalid_active_urls_found": 0,
            "invalid_urls": [],
        }

    conn = None
    try:
        # mode=ro avoids catalog_engine.db(), which can create tables or initialize
        # a missing DB as a side effect in a fresh CI checkout.
        uri = db_path.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "store_urls" not in tables:
            return {
                **base,
                "status": "SCHEMA_NOT_FOUND",
                "note": "The local database has no store_urls table; this is not a production inventory.",
                "active_deloox_urls_examined": 0,
                "invalid_active_urls_found": 0,
                "invalid_urls": [],
            }
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(store_urls)").fetchall()
        }
        required = {"store", "url", "slug", "active"}
        if not required <= columns:
            return {
                **base,
                "status": "SCHEMA_INCOMPLETE",
                "note": "The local store_urls schema is incomplete; no rows were classified.",
                "missing_columns": sorted(required - columns),
                "active_deloox_urls_examined": 0,
                "invalid_active_urls_found": 0,
                "invalid_urls": [],
            }
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT store,url,slug,active FROM store_urls WHERE lower(store)='deloox' AND active=1"
            ).fetchall()
        ]
        invalid = classify_invalid_urls(rows)
        return {
            **base,
            "status": "EMPTY_LOCAL_CATALOG" if not rows else "AUDIT_COMPLETE",
            "note": (
                "No active Deloox rows exist in this local environment; this is not a production inventory."
                if not rows else
                "This report covers only the local database opened by this process."
            ),
            "active_deloox_urls_examined": len(rows),
            "invalid_active_urls_found": len(invalid),
            "invalid_urls": invalid,
        }
    except sqlite3.Error as exc:
        return {
            **base,
            "status": "AUDIT_ERROR",
            "note": "Read-only local SQLite audit failed; no production inference is possible.",
            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
            "active_deloox_urls_examined": 0,
            "invalid_active_urls_found": 0,
            "invalid_urls": [],
        }
    finally:
        if conn is not None:
            conn.close()


def main() -> int:
    report = audit()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    # This diagnostic is allowed to complete even when a local DB is absent:
    # CI's empty local database is explicitly not a production-clean signal.
    # Missing local state or an absent schema is not a production-clean result,
    # but this report is a diagnostic rather than a production migration gate.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
