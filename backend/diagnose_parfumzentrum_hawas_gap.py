#!/usr/bin/env python3
"""Strict read-only ParfumZentrum Hawas gap diagnostic.

This endpoint does not import catalog_engine, call search_local(), invoke the
matcher, contact retailers, or start discovery/hydration/resync. It opens the
existing SQLite file with mode=ro and PRAGMA query_only=ON.
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter

router = APIRouter()

STORE = "parfumzentrum"
TARGETS = {
    "la_mer": {
        "terms": ["hawas", "la mer"],
        "url_fragments": ["z1254703", "la-mer", "la_mer"],
        "identifiers": ["1254703", "614514331279"],
        "known_url": "https://www.parfum-zentrum.de/rasasi-hawas-for-him-la-mer-eau-de-parfum-100-ml-man_z1254703/",
    },
    "verde": {
        "terms": ["hawas", "verde"],
        "url_fragments": ["verde"],
        "identifiers": [],
        "known_url": None,
    },
}
TABLES = (
    "store_urls",
    "store_products",
    "store_url_metadata",
    "hydration_queue",
    "catalog_discovery_queue",
    "catalog_search_fts",
)


def _db_path() -> Path:
    configured = os.environ.get("SCENTHUNTER_CATALOG_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parent / "store_catalog.sqlite3").resolve()


def _table_names(conn):
    return {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
    ).fetchall()}


def _columns(conn, table):
    return [r["name"] for r in conn.execute(
        f'PRAGMA table_info("{table}")'
    ).fetchall()]


def _safe_select(conn, table, clauses, params, limit=40):
    cols = _columns(conn, table)
    if not cols:
        return {"columns": [], "rows": [], "error": "TABLE_NOT_FOUND"}
    clauses = [c for c in clauses if c]
    where = " AND ".join(clauses) if clauses else "1=1"
    try:
        rows = conn.execute(
            f'SELECT * FROM "{table}" WHERE {where} LIMIT ?',
            tuple(params) + (limit,),
        ).fetchall()
        return {"columns": cols, "rows": [dict(r) for r in rows], "truncated_at": limit}
    except Exception as exc:
        return {"columns": cols, "rows": [], "error": f"{type(exc).__name__}: {exc}"}


def _target_rows(conn, table, target):
    cols = _columns(conn, table)
    if not cols:
        return {"columns": [], "rows": [], "error": "TABLE_NOT_FOUND"}
    clauses, params = [], []
    if "store" in cols:
        clauses.append("lower(store)=?")
        params.append(STORE)
    searchable = [c for c in ("url", "slug", "name", "brand", "search_text", "sku", "gtin", "mpn")
                  if c in cols]
    if not searchable:
        return {"columns": cols, "rows": [], "error": "NO_SEARCHABLE_COLUMNS"}
    # Return only records with target-specific evidence; generic "hawas" alone
    # is deliberately not sufficient to claim a target was found.
    signals = []
    signal_params = []
    for term in target["terms"]:
        term_clause = []
        for col in searchable:
            term_clause.append(f'lower(CAST("{col}" AS TEXT)) LIKE ?')
            signal_params.append("%" + term.lower().replace(" ", "%") + "%")
        signals.append("(" + " OR ".join(term_clause) + ")")
    for fragment in target["url_fragments"] + target["identifiers"]:
        fragment_clause = []
        for col in searchable:
            fragment_clause.append(f'lower(CAST("{col}" AS TEXT)) LIKE ?')
            signal_params.append("%" + fragment.lower() + "%")
        signals.append("(" + " OR ".join(fragment_clause) + ")")
    # Specific evidence may be any unique URL fragment/identifier, or both
    # product-name terms. Generic Hawas rows are not treated as target hits.
    specific_signal_indexes = range(2, len(signals))
    specific = [signals[i] for i in specific_signal_indexes]
    if len(signals) >= 2:
        specific.append("(" + signals[0] + " AND " + signals[1] + ")")
    if not specific:
        return {"columns": cols, "rows": [], "error": "NO_TARGET_SIGNATURE"}
    # Rebuild params for the actual OR expression to avoid unused bindings.
    params2 = []
    for fragment in target["url_fragments"] + target["identifiers"]:
        for _ in searchable:
            params2.append("%" + fragment.lower() + "%")
    for term in target["terms"]:
        for _ in searchable:
            params2.append("%" + term.lower().replace(" ", "%") + "%")
    # Clause order is URL fragments/IDs first, then both terms intersected.
    exact_clauses = []
    for fragment in target["url_fragments"] + target["identifiers"]:
        exact_clauses.append("(" + " OR ".join(
            f'lower(CAST("{c}" AS TEXT)) LIKE ?' for c in searchable
        ) + ")")
    term_clauses = []
    term_params = []
    for term in target["terms"]:
        term_clauses.append("(" + " OR ".join(
            f'lower(CAST("{c}" AS TEXT)) LIKE ?' for c in searchable
        ) + ")")
        term_params.extend(["%" + term.lower().replace(" ", "%") + "%"] * len(searchable))
    where_target_parts = exact_clauses[:]
    where_params = []
    for fragment in target["url_fragments"] + target["identifiers"]:
        where_params.extend(["%" + fragment.lower() + "%"] * len(searchable))
    if len(term_clauses) >= 2:
        where_target_parts.append("(" + " AND ".join(term_clauses) + ")")
        where_params.extend(term_params)
    where = []
    if "store" in cols:
        where.append("lower(store)=?")
        where_params.insert(0, STORE)
    where.append("(" + " OR ".join(where_target_parts) + ")")
    return _safe_select(conn, table, where, where_params, 60)


def _hawas_comparison(conn, table):
    cols = _columns(conn, table)
    if not cols:
        return {"columns": [], "rows": [], "error": "TABLE_NOT_FOUND"}
    searchable = [c for c in ("url", "slug", "name", "brand", "search_text", "sku", "gtin", "mpn")
                  if c in cols]
    if not searchable:
        return {"columns": cols, "rows": [], "error": "NO_SEARCHABLE_COLUMNS"}
    clauses = []
    params = []
    if "store" in cols:
        clauses.append("lower(store)=?")
        params.append(STORE)
    clauses.append("(" + " OR ".join(
        f'lower(CAST("{c}" AS TEXT)) LIKE ?' for c in searchable
    ) + ")")
    params.extend(["%hawas%"] * len(searchable))
    return _safe_select(conn, table, clauses, params, 30)


@router.get("/diagnose-parfumzentrum-hawas-gap")
def diagnose_parfumzentrum_hawas_gap(q: str = ""):
    started = time.monotonic()
    path = _db_path()
    selected = "verde" if "verde" in q.lower() else "la_mer" if ("la" in q.lower() or "mer" in q.lower()) else "both"
    report = {
        "diagnostic": "parfumzentrum-hawas-gap-strict-read-only-v3",
        "ok": False,
        "read_only": True,
        "database_written": False,
        "database_path_basename": path.name,
        "database_exists": path.is_file(),
        "store": STORE,
        "requested_query": q,
        "targets_checked": [selected] if selected != "both" else list(TARGETS),
        "production_search_called": False,
        "search_local_called": False,
        "product_matcher_called": False,
        "discovery_called": False,
        "hydration_called": False,
        "resync_called": False,
        "network_called": False,
        "schema": {},
        "target_rows": {},
        "hawas_comparison": {},
        "interpretation": {},
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
            report["schema"] = {
                table: _columns(conn, table) if table in names else None
                for table in TABLES
            }
            targets = report["targets_checked"]
            for key in targets:
                report["target_rows"][key] = {
                    table: _target_rows(conn, table, TARGETS[key]) if table in names else None
                    for table in TABLES
                }
            for table in ("store_products", "store_urls", "store_url_metadata", "catalog_search_fts"):
                report["hawas_comparison"][table] = (
                    _hawas_comparison(conn, table) if table in names else None
                )
            for key in targets:
                all_rows = report["target_rows"][key]
                present = {
                    table: len(data.get("rows", []))
                    for table, data in all_rows.items() if isinstance(data, dict)
                }
                report["interpretation"][key] = {
                    "target_specific_row_counts": present,
                    "present_in_any_scanned_table": any(present.values()),
                    "meaning": (
                        "TARGET_EVIDENCE_FOUND_IN_PERSISTENT_TABLES"
                        if any(present.values())
                        else "NO_TARGET_SPECIFIC_EVIDENCE_FOUND_IN_SCANNED_TABLES"
                    ),
                }
        finally:
            conn.close()
        report["ok"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    report["elapsed_sec"] = round(time.monotonic() - started, 3)
    return report
