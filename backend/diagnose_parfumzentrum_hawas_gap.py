"""Read-only, targeted ParfumZentrum Hawas gap diagnostic.
Uses schema-aware SQL LIKE filters; does not scan an arbitrary first 50,000 rows.
No scraper, discovery, hydration, ProductMatcher, resync, or database writes.
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from fastapi import APIRouter, Query

router = APIRouter()

TARGETS = {
    "la mer": {
        "label": "la_mer",
        "url": "https://www.parfum-zentrum.de/rasasi-hawas-for-him-la-mer-eau-de-parfum-100-ml-man_z1254703/",
        "sku": "1254703",
        "gtin": "614514331279",
        "terms": ("rasasi", "hawas", "la mer"),
    },
    "verde": {
        "label": "verde",
        "url": "",
        "sku": "",
        "gtin": "",
        "terms": ("rasasi", "hawas", "verde"),
    },
}


def _db_path() -> Path:
    configured = os.environ.get("SCENTHUNTER_CATALOG_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parent / "store_catalog.sqlite3").resolve()


def _columns(conn, table):
    return [r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')]


def _like_query(conn, table, columns, needles, limit=100):
    """Targeted SELECT; identifiers come from SQLite schema, values are bound."""
    available = [c for c in columns if c.lower() in {
        "store", "url", "slug", "name", "brand", "product_name",
        "product_brand", "sku", "gtin", "mpn", "search_text",
        "state", "fetch_status", "active", "last_error",
        "last_http_status", "attempts", "available_at", "fetched_at",
        "discovered_at", "last_finished_at", "source"
    }]
    searchable = [c for c in available if c.lower() not in {
        "store", "state", "fetch_status", "active", "last_error",
        "last_http_status", "attempts", "available_at", "fetched_at",
        "discovered_at", "last_finished_at", "source"
    }]
    if not searchable:
        return {"columns": columns, "rows": [], "note": "NO_SEARCHABLE_COLUMNS"}
    # Each result must contain at least one strong identifying signal.
    groups, params = [], []
    for needle in needles:
        if not needle:
            continue
        groups.append("(" + " OR ".join(f'lower(CAST("{c}" AS TEXT)) LIKE ?' for c in searchable) + ")")
        params.extend([f"%{needle.lower()}%"] * len(searchable))
    if not groups:
        return {"columns": columns, "rows": [], "note": "NO_QUERY_TERMS"}
    where = []
    if "store" in columns:
        where.append("lower(store) = 'parfumzentrum'")
    where.append("(" + " OR ".join(groups) + ")")
    try:
        rows = conn.execute(
            f'SELECT * FROM "{table}" WHERE ' + " AND ".join(where) + " LIMIT ?",
            tuple(params) + (limit,)
        ).fetchall()
        return {"columns": columns, "rows": [dict(r) for r in rows]}
    except Exception as exc:
        return {"columns": columns, "rows": [], "error": f"{type(exc).__name__}: {exc}"}


def _compact_row(table, row):
    allowed = {
        "store", "url", "slug", "name", "brand", "product_name",
        "product_brand", "sku", "gtin", "mpn", "size_ml", "price",
        "currency", "availability", "active", "fetch_status", "state",
        "attempts", "available_at", "last_error", "last_http_status",
        "fetched_at", "discovered_at", "last_finished_at", "source",
        "search_text", "depth", "priority"
    }
    return {"table": table, **{k: v for k, v in row.items() if k.lower() in allowed}}


@router.get("/diagnose-parfumzentrum-hawas-gap")
def diagnose_parfumzentrum_hawas_gap(q: str = Query("La Mer")):
    started = time.monotonic()
    query = str(q or "La Mer").strip().lower()
    target_key = "verde" if "verde" in query else "la mer"
    target = TARGETS[target_key]
    # Search by separate, short signals to catch differences in word order and punctuation.
    needles = list(dict.fromkeys([
        target_key, "hawas", target["sku"], target["gtin"],
        "rasasi hawas la mer" if target_key == "la mer" else "rasasi hawas verde",
    ]))
    needles = [x for x in needles if x]
    path = _db_path()
    report = {
        "diagnostic": "parfumzentrum-hawas-gap-read-only-v2",
        "ok": False, "store": "parfumzentrum", "query": q,
        "target": target, "database_path_basename": path.name,
        "database_exists": path.is_file(), "read_only": True,
        "database_written": False, "scraper_called": False,
        "discovery_called": False, "hydration_called": False,
        "product_matcher_called": False, "production_search_called": False,
        "search_local_called": False, "tables": {},
    }
    if not path.is_file():
        report["error"] = "CATALOG_DATABASE_FILE_NOT_FOUND"
        report["elapsed_sec"] = round(time.monotonic() - started, 3)
        return report

    try:
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        try:
            names = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )}
            for table in ("store_urls", "store_products", "hydration_queue",
                          "store_url_metadata", "catalog_discovery_queue",
                          "catalog_search_fts"):
                if table not in names:
                    report["tables"][table] = {"error": "TABLE_NOT_FOUND"}
                    continue
                cols = _columns(conn, table)
                result = _like_query(conn, table, cols, needles, limit=100)
                result["rows"] = [_compact_row(table, r) for r in result.get("rows", [])]
                report["tables"][table] = result
        finally:
            conn.close()

        try:
            from catalog_engine import search_local
            search_query = "Rasasi Hawas " + ("Verde" if target_key == "verde" else "La Mer")
            projected = search_local(search_query, per_store=100, search_terms=[search_query])
            report["search_local_called"] = True
            matching = []
            for row in list(projected or []):
                if not isinstance(row, dict) or str(row.get("store", "")).lower() != "parfumzentrum":
                    continue
                hay = " ".join(str(row.get(k) or "") for k in ("name", "brand", "url", "sku", "gtin")).lower()
                if target_key in hay or (target_key == "la mer" and "la mer" in hay):
                    matching.append({k: row.get(k) for k in (
                        "store", "name", "brand", "url", "price", "availability",
                        "size_ml", "fetch_status", "source", "sku", "gtin"
                    ) if k in row})
            report["search_local_rows"] = matching[:100]
        except Exception as exc:
            report["search_local_error"] = f"{type(exc).__name__}: {exc}"

        table_hits = {
            name: value.get("rows", [])
            for name, value in report["tables"].items()
            if isinstance(value, dict) and value.get("rows")
        }
        report["persistent_table_hit_count"] = sum(len(v) for v in table_hits.values())
        report["persistent_matches_by_table"] = {k: len(v) for k, v in table_hits.items()}
        if not table_hits:
            report["conclusion"] = "NO_TARGETED_MATCH_IN_CATALOG_TABLES"
        elif not report.get("search_local_rows"):
            report["conclusion"] = "TARGETED_CATALOG_ROWS_FOUND_BUT_NOT_PROJECTED_BY_SEARCH_LOCAL"
        else:
            report["conclusion"] = "TARGETED_CATALOG_ROWS_AND_SEARCH_LOCAL_ROWS_FOUND"
        report["ok"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    report["elapsed_sec"] = round(time.monotonic() - started, 3)
    return report
