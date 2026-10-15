"""Read-only ParfumZentrum Hawas gap diagnostic.
No scraper, discovery, hydration, ProductMatcher, or database writes.
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Query

router = APIRouter()

KNOWN_TARGETS = {
    "la_mer": {
        "url": "https://www.parfum-zentrum.de/rasasi-hawas-for-him-la-mer-eau-de-parfum-100-ml-man_z1254703/",
        "sku": "1254703",
        "gtin": "614514331279",
        "terms": ["rasasi", "hawas", "la mer"],
    },
    "verde": {
        "url": "",
        "sku": "",
        "gtin": "",
        "terms": ["rasasi", "hawas", "verde"],
    },
}


def _db_path() -> Path:
    configured = os.environ.get("SCENTHUNTER_CATALOG_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parent / "store_catalog.sqlite3").resolve()


def _tables(conn):
    return conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()


def _columns(conn, table):
    # table name comes only from sqlite_master, not user input
    return [row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")')]


def _as_text(value):
    return str(value or "").strip()


def _row_matches(row, target):
    vals = " ".join(_as_text(v) for v in row.values()).lower()
    url = _as_text(target.get("url")).lower()
    sku = _as_text(target.get("sku")).lower()
    gtin = _as_text(target.get("gtin")).lower()
    terms = [x.lower() for x in target.get("terms", []) if x]
    exact_url = bool(url and url in vals)
    exact_sku = bool(sku and re.search(rf"(?<!\d){re.escape(sku)}(?!\d)", vals))
    exact_gtin = bool(gtin and gtin in vals)
    name_hit = bool(terms and all(term in vals for term in terms))
    return exact_url or exact_sku or exact_gtin or name_hit, {
        "exact_url": exact_url, "exact_sku": exact_sku,
        "exact_gtin": exact_gtin, "all_name_terms": name_hit,
    }


@router.get("/diagnose-parfumzentrum-hawas-gap")
def diagnose_parfumzentrum_hawas_gap(q: str = Query("La Mer")):
    started = time.monotonic()
    query = str(q or "").strip().lower()
    if "verde" in query:
        label = "verde"
    else:
        label = "la_mer"
    target = KNOWN_TARGETS[label]
    path = _db_path()
    report = {
        "diagnostic": "parfumzentrum-hawas-gap-read-only-v1",
        "ok": False,
        "store": "parfumzentrum",
        "query": q,
        "target": target,
        "database_path_basename": path.name,
        "database_exists": path.is_file(),
        "read_only": True,
        "database_written": False,
        "scraper_called": False,
        "discovery_called": False,
        "hydration_called": False,
        "product_matcher_called": False,
        "production_search_called": False,
        "search_local_called": False,
        "tables_checked": [],
        "persistent_matches": [],
        "search_local_rows": [],
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
            for table_row in _tables(conn):
                table = table_row["name"]
                cols = _columns(conn, table)
                # Search only tables that can plausibly hold retailer URL/product data.
                if not any(c.lower() in {"url", "product_url", "canonical_url"} for c in cols):
                    continue
                report["tables_checked"].append({"table": table, "columns": cols})
                try:
                    rows = conn.execute(f'SELECT * FROM "{table}" LIMIT 50000').fetchall()
                except Exception as exc:
                    report.setdefault("table_errors", []).append(
                        {"table": table, "error": f"{type(exc).__name__}: {exc}"}
                    )
                    continue
                for sqlite_row in rows:
                    row = dict(sqlite_row)
                    store_val = _as_text(row.get("store")).lower()
                    if store_val and store_val != "parfumzentrum":
                        continue
                    matched, evidence = _row_matches(row, target)
                    if matched:
                        # Keep diagnostic output bounded and avoid exposing unrelated columns.
                        report["persistent_matches"].append({
                            "table": table,
                            "evidence": evidence,
                            "row": {k: row.get(k) for k in cols if k.lower() in {
                                "store", "url", "product_url", "canonical_url", "slug",
                                "product_name", "name", "title", "product_brand", "brand",
                                "sku", "gtin", "ean", "active", "fetch_status", "status",
                                "last_fetched_at", "updated_at", "discovered_at",
                                "hydration_status", "attempts", "last_error"
                            }},
                        })
                        if len(report["persistent_matches"]) >= 30:
                            break
                if len(report["persistent_matches"]) >= 30:
                    break
        finally:
            conn.close()

        # This calls only the existing local catalog projection. It does not call /search.
        try:
            from catalog_engine import search_local
            search_query = "Rasasi Hawas " + ("Verde" if label == "verde" else "La Mer")
            rows = search_local(search_query, per_store=100, search_terms=[search_query])
            report["search_local_called"] = True
            for item in list(rows or []):
                if not isinstance(item, dict):
                    continue
                if _as_text(item.get("store")).lower() != "parfumzentrum":
                    continue
                haystack = " ".join(_as_text(item.get(k)) for k in (
                    "name", "brand", "url", "size_ml", "sku", "gtin"
                )).lower()
                if ("verde" if label == "verde" else "la mer") in haystack:
                    report["search_local_rows"].append({
                        k: item.get(k) for k in (
                            "store", "name", "brand", "url", "price", "availability",
                            "size_ml", "fetch_status", "source", "sku", "gtin"
                        ) if k in item
                    })
        except Exception as exc:
            report["search_local_error"] = f"{type(exc).__name__}: {exc}"

        persistent = report["persistent_matches"]
        projected = report["search_local_rows"]
        if not persistent:
            report["conclusion"] = "NO_MATCH_FOUND_IN_SCANNED_URL_TABLES"
        elif not projected:
            report["conclusion"] = "PERSISTENT_MATCH_FOUND_BUT_NOT_RETURNED_BY_SEARCH_LOCAL"
        else:
            report["conclusion"] = "PERSISTENT_MATCH_AND_SEARCH_LOCAL_ROW_FOUND"
        report["ok"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"

    report["elapsed_sec"] = round(time.monotonic() - started, 3)
    return report
