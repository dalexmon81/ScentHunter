"""Export the next-engine current offers as a bounded, read-only shadow snapshot."""
from __future__ import annotations
import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any


def export_next_catalog(db_path: str | Path, output_path: str | Path, store: str | None = None,
                        limit: int = 50000) -> dict[str, Any]:
    if limit < 1 or limit > 500000:
        raise ValueError("limit must be between 1 and 500000")
    db = Path(db_path).expanduser().resolve(strict=True)
    out = Path(output_path).expanduser().resolve()
    if not db.is_file():
        raise ValueError("database path is not a file")
    if db == out:
        raise ValueError("output path must not be the database file")
    conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=3)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"offers", "variants", "products"}
        missing = required - tables
        if missing:
            raise ValueError("not a next-engine database; missing tables: " + ", ".join(sorted(missing)))
        sql = """SELECT o.store,o.product_url AS url,p.canonical_name AS name,p.brand,
          p.gtin,p.mpn,v.size_ml,v.concentration,v.pack_count,v.gender,
          o.price_minor / 100.0 AS price,o.currency,o.availability,o.last_valid_at AS fetched_at,
          o.source_sku AS sku,o.is_current
          FROM offers o JOIN variants v USING(variant_id) JOIN products p USING(product_id)
          WHERE o.is_current=1"""
        args: list[Any] = []
        if store:
            sql += " AND lower(o.store)=?"
            args.append(store.strip().lower())
        sql += " ORDER BY o.store,o.product_url LIMIT ?"
        args.append(limit + 1)
        fetched = [dict(r) for r in conn.execute(sql, args).fetchall()]
        truncated = len(fetched) > limit
        rows = fetched[:limit]
    finally:
        conn.close()
    snapshot = {"schema_version": 1, "source": "scenthunter_next_sqlite", "read_only": True,
                "database_written": False, "network_requests": 0,
                "store_filter": store.strip().lower() if store else None, "limit": limit,
                "rows": rows, "truncated": truncated}
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export next-engine offers read-only for shadow comparison")
    parser.add_argument("--db", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--store")
    parser.add_argument("--limit", type=int, default=50000)
    args = parser.parse_args(argv)
    try:
        data = export_next_catalog(args.db, args.output, args.store, args.limit)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(json.dumps({"output": str(Path(args.output).resolve()), "rows": len(data["rows"]),
                      "truncated": data["truncated"], "read_only": True}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
