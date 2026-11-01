#!/usr/bin/env python3
"""Read-only Easycosmetic production-catalog diagnostic.

Replaces the broken variant-discovery diagnostic. It deliberately does not
import catalog_engine.db(), because db() calls _ensure_schema() and can mutate
the database. SQLite is opened with mode=ro; no network, discovery, hydration,
matcher, resync, or writes are performed.
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter

router = APIRouter()

TARGETS = {
    "donna_30": "https://www.easycosmetic.be/valentino/donna-born-in-roma/valentino-donna-born-in-roma-coral-fantasy-eau-de-parfum-spray.aspx?variant=78097",
    "donna_50": "https://www.easycosmetic.be/valentino/donna-born-in-roma/valentino-donna-born-in-roma-coral-fantasy-eau-de-parfum-spray.aspx?variant=78098",
    "donna_100": "https://www.easycosmetic.be/valentino/donna-born-in-roma/valentino-donna-born-in-roma-coral-fantasy-eau-de-parfum-spray.aspx?variant=78099",
    "donna_10": "https://www.easycosmetic.be/valentino/donna-born-in-roma/valentino-donna-born-in-roma-coral-fantasy-eau-de-parfum-spray.aspx?variant=107764",
}
TARGET_PATH = urlparse(next(iter(TARGETS.values()))).path.lower()


def _db_path() -> Path:
    configured = os.environ.get("SCENTHUNTER_CATALOG_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parent / "store_catalog.sqlite3").resolve()


def _table_names(conn):
    return {row["name"] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()}


def _columns(conn, table):
    return [row["name"] for row in conn.execute(
        f'PRAGMA table_info("{table}")').fetchall()]


def _dict_rows(conn, table, where, params=(), limit=30):
    columns = _columns(conn, table)
    if not columns:
        return {"columns": [], "rows": [], "error": "TABLE_NOT_FOUND"}
    try:
        rows = conn.execute(
            f'SELECT * FROM "{table}" WHERE {where} LIMIT ?',
            tuple(params) + (limit,)).fetchall()
        return {"columns": columns, "rows": [dict(row) for row in rows]}
    except Exception as exc:
        return {"columns": columns, "rows": [], "error": f"{type(exc).__name__}: {exc}"}


def _url_rows(conn, table, target_url):
    columns = _columns(conn, table)
    if not columns:
        return {"columns": [], "exact": [], "same_product_path": [], "error": "TABLE_NOT_FOUND"}
    if "url" not in columns:
        return {"columns": columns, "exact": [], "same_product_path": [], "error": "NO_URL_COLUMN"}
    store_clause = "store = 'easycosmetic'" if "store" in columns else "1=1"
    exact = _dict_rows(conn, table, f"{store_clause} AND url = ?", (target_url,), 10)
    same = _dict_rows(conn, table, f"{store_clause} AND lower(url) LIKE ?",
                      (f"%{TARGET_PATH}%",), 50)
    return {"columns": columns, "exact": exact.get("rows", []),
            "same_product_path": same.get("rows", []),
            "exact_error": exact.get("error"), "path_error": same.get("error")}


def _fts_rows(conn, table, target_url):
    columns = _columns(conn, table)
    if not columns:
        return {"columns": [], "rows": [], "error": "TABLE_NOT_FOUND"}
    candidates = [c for c in ("url", "store", "name", "title", "text", "content", "search_text") if c in columns]
    if not candidates:
        return {"columns": columns, "rows": [], "error": "NO_SEARCHABLE_COLUMNS"}
    clauses, params = [], []
    if "url" in columns:
        clauses.extend(["url = ?", "lower(url) LIKE ?"])
        params.extend([target_url, f"%{TARGET_PATH}%"])
    for col in (c for c in candidates if c not in ("url", "store")):
        clauses.append(f'lower(CAST("{col}" AS TEXT)) LIKE ?')
        params.append("%coral%fantasy%")
    store_filter = "store = 'easycosmetic' AND " if "store" in columns else ""
    try:
        rows = conn.execute(
            f'SELECT * FROM "{table}" WHERE {store_filter}(' + " OR ".join(clauses) + ") LIMIT 50",
            tuple(params)).fetchall()
        return {"columns": columns, "rows": [dict(row) for row in rows]}
    except Exception as exc:
        return {"columns": columns, "rows": [], "error": f"{type(exc).__name__}: {exc}"}


@router.get("/diagnose-easycosmetic-variant-discovery")
def diagnose_easycosmetic_variant_discovery():
    started = time.monotonic()
    path = _db_path()
    report = {
        "diagnostic": "easycosmetic-production-catalog-read-only-v2",
        "ok": False, "read_only": True, "database_written": False,
        "production_search_called": False, "resync_called": False,
        "product_matcher_called": False, "catalog_discovery_worker_called": False,
        "hydration_called": False, "network_called": False,
        "store": "easycosmetic", "database_path_basename": path.name,
        "database_exists": path.is_file(), "targets": TARGETS,
        "schema": {}, "persistent_rows": {},
    }
    if not path.is_file():
        report["error"] = "CATALOG_DATABASE_FILE_NOT_FOUND"
        report["elapsed_sec"] = round(time.monotonic() - started, 3)
        return report
    try:
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        try:
            names = _table_names(conn)
            relevant = ("store_urls", "hydration_queue", "store_products", "catalog_search_fts", "sync_state")
            report["schema"] = {name: _columns(conn, name) if name in names else None for name in relevant}
            for label, url in TARGETS.items():
                report["persistent_rows"][label] = {
                    "store_urls": _url_rows(conn, "store_urls", url) if "store_urls" in names else None,
                    "hydration_queue": _url_rows(conn, "hydration_queue", url) if "hydration_queue" in names else None,
                    "store_products": _url_rows(conn, "store_products", url) if "store_products" in names else None,
                    "catalog_search_fts": _fts_rows(conn, "catalog_search_fts", url) if "catalog_search_fts" in names else None,
                }
            if "sync_state" in names:
                cols = _columns(conn, "sync_state")
                report["sync_state_easycosmetic"] = _dict_rows(conn, "sync_state", "store = 'easycosmetic'", (), 10) if "store" in cols else {"columns": cols, "error": "NO_STORE_COLUMN"}
        finally:
            conn.close()
        report["ok"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    report["elapsed_sec"] = round(time.monotonic() - started, 3)
    return report
