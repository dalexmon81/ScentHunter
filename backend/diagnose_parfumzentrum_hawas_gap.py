"""Strict read-only diagnostic for the two missing ParfumZentrum Hawas offers.

Route: GET /diagnose-parfumzentrum-hawas-index?q=La%20Mer
        GET /diagnose-parfumzentrum-hawas-index?q=Verde
        GET /diagnose-parfumzentrum-hawas-index?q=Hawas%20Ice

This module deliberately does not call catalog_engine.db(), search_local(), ProductMatcher,
scrapers, discovery, hydration, or any function that may mutate production state.
It opens the existing SQLite database in SQLite read-only mode.
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

router = APIRouter()


def _resolve_db_path() -> Path:
    """Resolve the catalog DB path without opening it through catalog_engine."""
    env_candidates = (
        os.getenv("SCENTHUNTER_DB_PATH"),
        os.getenv("CATALOG_DB_PATH"),
        os.getenv("DATABASE_PATH"),
        os.getenv("SQLITE_DB_PATH"),
    )
    for value in env_candidates:
        if value:
            candidate = Path(value).expanduser()
            if candidate.is_file():
                return candidate.resolve()

    # Match common project/runtime locations without invoking DB initialization.
    here = Path(__file__).resolve()
    candidates = (
        here.parent / "store_catalog.sqlite3",
        here.parent.parent / "store_catalog.sqlite3",
        Path("/app/store_catalog.sqlite3"),
        Path("/app/backend/store_catalog.sqlite3"),
        Path("/data/store_catalog.sqlite3"),
        Path("/data/store_catalog.db"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    # Read path constants only; do not call catalog_engine.db().
    try:
        import catalog_engine  # type: ignore
        for attr in ("DB_PATH", "DATABASE_PATH", "DB_FILE", "CATALOG_DB_PATH"):
            value = getattr(catalog_engine, attr, None)
            if value:
                candidate = Path(str(value)).expanduser()
                if candidate.is_file():
                    return candidate.resolve()
    except Exception:
        pass

    raise FileNotFoundError("Could not resolve existing catalog SQLite database path")


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        return [str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')]
    except sqlite3.Error:
        return []


def _dict_rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...], limit: int = 12) -> list[dict[str, Any]]:
    try:
        cur = conn.execute(sql, params)
        names = [item[0] for item in (cur.description or [])]
        out = []
        for row in cur.fetchmany(limit):
            item = {}
            for name, value in zip(names, row):
                if isinstance(value, bytes):
                    value = value[:120].decode("utf-8", "replace")
                item[name] = value
            out.append(item)
        return out
    except sqlite3.Error as exc:
        return [{"query_error": f"{type(exc).__name__}: {exc}"}]


def _like_any(columns: list[str], terms: list[str]) -> tuple[str, list[Any]]:
    usable = [c for c in columns if c in {
        "url", "slug", "name", "brand", "sku", "gtin", "mpn", "search_text"
    }]
    if not usable:
        return "0", []
    clauses, params = [], []
    for col in usable:
        for term in terms:
            clauses.append(f'lower(COALESCE("{col}", \'\')) LIKE ?')
            params.append("%" + term.lower() + "%")
    return "(" + " OR ".join(clauses) + ")", params


@router.get("/diagnose-parfumzentrum-hawas-index")
def diagnose_parfumzentrum_hawas_index(q: str = Query(default="La Mer", max_length=80)):
    started = time.monotonic()
    query = (q or "La Mer").strip()
    lowered = query.lower()
    if "ice" in lowered:
        label = "hawas_ice"
        patterns = [
            "rasasi-hawas-hawas-ice-eau-de-parfum-100-ml-man_z913265",
            "rasasi hawas ice",
            "hawas ice",
            "913265",
            "614514331040",
        ]
        exact_url = "https://www.parfum-zentrum.de/rasasi-hawas-hawas-ice-eau-de-parfum-100-ml-man_z913265/"
        sku = "913265"
        gtin = "614514331040"
    elif "verde" in lowered:
        label = "verde"
        patterns = ["hawas-verde", "hawas verde", "rasasi-hawas-verde", "rasasi hawas verde", "verde"]
        exact_url = ""
        sku = ""
        gtin = ""
    else:
        label = "la_mer"
        patterns = [
            "rasasi-hawas-for-him-la-mer",
            "hawas for him la mer",
            "hawas la mer",
            "1254703",
            "614514331279",
        ]
        exact_url = "https://www.parfum-zentrum.de/rasasi-hawas-for-him-la-mer-eau-de-parfum-100-ml-man_z1254703/"
        sku = "1254703"
        gtin = "614514331279"

    result: dict[str, Any] = {
        "diagnostic": "parfumzentrum-hawas-index-read-only-v1",
        "ok": False,
        "read_only": True,
        "database_written": False,
        "store": "parfumzentrum",
        "query": query,
        "target": {"label": label, "url": exact_url or None, "sku": sku or None, "gtin": gtin or None},
        "calls": {
            "search_local": False, "production_search": False, "product_matcher": False,
            "scraper": False, "discovery": False, "hydration": False, "resync": False,
            "network": False,
        },
    }

    try:
        db_path = _resolve_db_path()
        result["database_path_basename"] = db_path.name
        uri = db_path.as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=3)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=3000")

        tables = {
            str(row[0]) for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        target_tables = [
            "store_urls", "store_products", "store_url_metadata",
            "hydration_queue", "catalog_discovery_queue", "catalog_search_fts",
        ]
        result["tables"] = {}
        for table in target_tables:
            if table not in tables:
                result["tables"][table] = {"exists": False, "columns": [], "rows": []}
                continue

            cols = _columns(conn, table)
            store_filter = 'lower("store")=? AND ' if "store" in cols else ""
            where, like_params = _like_any(cols, patterns)
            params: list[Any] = []
            if "store" in cols:
                params.append("parfumzentrum")
            params.extend(like_params)
            order = ""
            if table == "store_urls":
                order = " ORDER BY CASE WHEN lower(COALESCE(url,'')) LIKE '%hawas%' THEN 0 ELSE 1 END, active DESC"
            elif table == "store_products":
                order = " ORDER BY CASE WHEN lower(COALESCE(url,'')) LIKE '%hawas%' THEN 0 ELSE 1 END, fetched_at DESC"
            sql = f'SELECT * FROM "{table}" WHERE {store_filter}{where}{order} LIMIT 20'
            rows = _dict_rows(conn, sql, tuple(params), limit=20)
            result["tables"][table] = {
                "exists": True,
                "columns": cols,
                "match_count_returned": len(rows),
                "rows": rows,
            }

        # Explicit joined row reveals URL discovery, hydration, and FTS publication in one place.
        if "store_urls" in tables and "store_products" in tables:
            if label in {"la_mer", "hawas_ice"}:
                result["joined_target"] = _dict_rows(
                    conn,
                    """SELECT u.store,u.url,u.slug,u.active,
                              p.name,p.brand,p.sku,p.gtin,p.price,p.currency,
                              p.availability,p.fetch_status,
                              f.search_text AS fts_search_text
                         FROM store_urls u
                         LEFT JOIN store_products p ON p.store=u.store AND p.url=u.url
                         LEFT JOIN catalog_search_fts f ON f.store=u.store AND f.url=u.url
                        WHERE lower(u.store)='parfumzentrum'
                          AND (u.url=? OR lower(COALESCE(p.sku,''))=? OR lower(COALESCE(p.gtin,''))=?)
                        LIMIT 10""",
                    (exact_url, sku.lower(), gtin.lower()),
                    10,
                )
            else:
                result["joined_target"] = _dict_rows(
                    conn,
                    """SELECT u.store,u.url,u.slug,u.active,
                              p.name,p.brand,p.sku,p.gtin,p.price,p.currency,
                              p.availability,p.fetch_status,
                              f.search_text AS fts_search_text
                         FROM store_urls u
                         LEFT JOIN store_products p ON p.store=u.store AND p.url=u.url
                         LEFT JOIN catalog_search_fts f ON f.store=u.store AND f.url=u.url
                        WHERE lower(u.store)='parfumzentrum'
                          AND (lower(COALESCE(u.url,'')) LIKE '%hawas%verde%'
                            OR lower(COALESCE(u.slug,'')) LIKE '%hawas%verde%'
                            OR (lower(COALESCE(p.name,'')) LIKE '%hawas%'
                                AND lower(COALESCE(p.name,'')) LIKE '%verde%'))
                        LIMIT 20""",
                    (),
                    20,
                )

        # Exact FTS candidate lookup, read-only. Does not initialize or rebuild the index.
        if "catalog_search_fts" in tables:
            fts_terms = (
                ["hawas", "rasasi", "verde"] if label == "verde"
                else ["hawas", "rasasi", "ice"] if label == "hawas_ice"
                else ["hawas", "rasasi", "la", "mer"]
            )
            fts_query = " AND ".join('"' + term + '"' for term in fts_terms)
            result["fts_match"] = _dict_rows(
                conn,
                "SELECT store,url,search_text FROM catalog_search_fts WHERE catalog_search_fts MATCH ? AND lower(store)='parfumzentrum' LIMIT 20",
                (fts_query,),
                20,
            )
        else:
            result["fts_match"] = {"error": "catalog_search_fts table absent"}

        conn.close()
        result["ok"] = True
        result["elapsed_sec"] = round(time.monotonic() - started, 3)
        return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["elapsed_sec"] = round(time.monotonic() - started, 3)
        return result
