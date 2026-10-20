"""Export legacy ScentHunter catalog rows from SQLite in strict read-only mode.

No application imports, migrations, network calls, or database writes occur here.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
TABLE_COLUMNS = {
    "store_urls": ("store", "url", "slug", "lastmod", "discovered_at", "active"),
    "store_products": (
        "store", "url", "name", "brand", "image", "sku", "gtin", "mpn",
        "size_ml", "concentration", "gender", "price", "currency",
        "availability", "fetched_at", "fetch_status",
    ),
    "store_product_variants": (
        "store", "url", "variant_key", "name", "brand", "image", "sku",
        "gtin", "mpn", "size_ml", "concentration", "gender", "price",
        "currency", "availability", "fetched_at", "variant_url",
    ),
}


def _open_read_only(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"database path is not a file: {path}")
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def export_catalog(db_path: str | Path, output_path: str | Path, store: str | None = None,
                   limit_per_table: int = 50000) -> dict[str, Any]:
    """Write a capped JSON snapshot; database is opened using SQLite mode=ro."""
    if limit_per_table < 1 or limit_per_table > 500000:
        raise ValueError("limit_per_table must be between 1 and 500000")
    db_file = Path(db_path).expanduser().resolve(strict=True)
    out_file = Path(output_path).expanduser().resolve()
    if db_file == out_file:
        raise ValueError("output path must not be the database file")
    if out_file.exists() and out_file == db_file:
        raise ValueError("output path must not overwrite the database file")

    tables_out: dict[str, Any] = {}
    conn = _open_read_only(db_file)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, expected_columns in TABLE_COLUMNS.items():
            if table not in tables:
                tables_out[table] = {"present": False, "columns": [], "rows": [], "truncated": False}
                continue
            actual = {r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')}
            columns = [col for col in expected_columns if col in actual]
            if not columns:
                tables_out[table] = {"present": True, "columns": [], "rows": [], "truncated": False}
                continue
            sql = "SELECT " + ",".join('"' + col + '"' for col in columns) + f' FROM "{table}"'
            params: tuple[Any, ...] = ()
            if store:
                if "store" not in actual:
                    tables_out[table] = {"present": True, "columns": columns, "rows": [], "truncated": False}
                    continue
                sql += ' WHERE "store"=?'
                params = (store.strip().lower(),)
            sql += " LIMIT ?"
            params += (limit_per_table + 1,)
            fetched = [dict(row) for row in conn.execute(sql, params).fetchall()]
            truncated = len(fetched) > limit_per_table
            tables_out[table] = {
                "present": True,
                "columns": columns,
                "rows": fetched[:limit_per_table],
                "truncated": truncated,
            }
    finally:
        conn.close()

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "source": "scenthunter_legacy_sqlite",
        "read_only": True,
        "database_written": False,
        "network_requests": 0,
        "store_filter": store.strip().lower() if store else None,
        "limit_per_table": limit_per_table,
        "tables": tables_out,
    }
    out_file.parent.mkdir(parents=True, exist_ok=True)
    temp = out_file.with_suffix(out_file.suffix + ".tmp")
    temp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, out_file)
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export ScentHunter legacy catalog from SQLite in read-only mode")
    parser.add_argument("--db", required=True, help="Exact path to the existing SQLite database")
    parser.add_argument("--output", required=True, help="JSON snapshot destination; must not be the database path")
    parser.add_argument("--store", help="Optional retailer filter, e.g. deloox")
    parser.add_argument("--limit-per-table", type=int, default=50000, help="Maximum rows per table (1..500000)")
    args = parser.parse_args(argv)
    try:
        snapshot = export_catalog(args.db, args.output, args.store, args.limit_per_table)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "output": str(Path(args.output).resolve()),
        "read_only": snapshot["read_only"],
        "store_filter": snapshot["store_filter"],
        "tables": {name: {"present": data["present"], "rows": len(data["rows"]), "truncated": data["truncated"]}
                   for name, data in snapshot["tables"].items()},
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
