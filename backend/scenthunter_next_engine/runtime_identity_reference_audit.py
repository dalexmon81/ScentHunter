"""Read-only inventory of references to selected catalog identities in a SQLite DB.

This tool never writes to the database. It opens SQLite in URI mode=ro and
sets query_only. The JSON report contains table/column names and counts, not
full row contents.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

DEFAULT_IDS = (
    "SH-AUTO-0288",
    "SH-AUTO-0018",
    "SH-0043",
    "SH-AUTO-0019",
    "VAR-89c2a2a86bedb3c5",
    "VAR-09a73d0a5594cf49",
    "VAR-30ce093fd9e9ab47",
    "VAR-46b03c1f1cff0a6e",
    "VAR-f79ca5b3b5fd237f",
    "VAR-69fbeda0c7a3c691",
    "VAR-b6adcf86ddaab498",
    "VAR-d2e93b41952c6151",
)


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def audit_database(db_path: str | Path, target_ids: Iterable[str] = DEFAULT_IDS) -> dict:
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"SQLite database file not found: {path}")
    targets = tuple(dict.fromkeys(str(item) for item in target_ids if str(item)))
    if not targets:
        raise ValueError("At least one target ID is required")

    uri = path.as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        schema = connection.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name"
        ).fetchall()
        matches = []
        scanned_columns = 0
        scanned_objects = 0
        for obj in schema:
            object_name = obj["name"]
            object_type = obj["type"]
            # table_xinfo includes generated/hidden columns; audit visible columns only.
            columns = connection.execute(
                f"PRAGMA table_info({_quote(object_name)})"
            ).fetchall()
            if not columns:
                continue
            scanned_objects += 1
            for col in columns:
                column_name = col["name"]
                scanned_columns += 1
                expression = f"CAST({_quote(column_name)} AS TEXT)"
                predicates = " OR ".join(f"{expression} LIKE ?" for _ in targets)
                params = tuple(f"%{target}%" for target in targets)
                try:
                    rows = connection.execute(
                        f"SELECT {expression} AS value FROM {_quote(object_name)} "
                        f"WHERE {predicates} LIMIT 10001",
                        params,
                    ).fetchall()
                except sqlite3.DatabaseError as exc:
                    matches.append({
                        "object": object_name,
                        "object_type": object_type,
                        "column": column_name,
                        "error": type(exc).__name__,
                    })
                    continue
                if rows:
                    counts = {target: 0 for target in targets}
                    for row in rows:
                        value = row["value"] or ""
                        for target in targets:
                            if target in value:
                                counts[target] += 1
                    matches.append({
                        "object": object_name,
                        "object_type": object_type,
                        "column": column_name,
                        "rows_with_match": len(rows),
                        "count_capped": len(rows) > 10000,
                        "target_occurrences": {k: v for k, v in counts.items() if v},
                    })
        return {
            "schema_version": 1,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "database_path": str(path),
            "read_only": True,
            "database_mutated": False,
            "query_only_enabled": True,
            "target_ids": list(targets),
            "objects_scanned": scanned_objects,
            "columns_scanned": scanned_columns,
            "matching_columns": len(matches),
            "matches": matches,
            "limitations": [
                "Counts are rows containing each ID in a column, not unique references.",
                "Counts are capped at 10000 matching rows per column.",
                "SQLite tables/views only; external systems, logs, caches, and source code are outside this inventory.",
            ],
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        default=os.environ.get("SCENTHUNTER_CATALOG_DB", "backend/store_catalog.sqlite3"),
        help="Path to the existing SQLite catalog database (default: SCENTHUNTER_CATALOG_DB or backend/store_catalog.sqlite3)",
    )
    parser.add_argument("--output", default="runtime-identity-reference-audit.json")
    parser.add_argument("--ids", nargs="*", default=list(DEFAULT_IDS), help="Optional replacement target IDs")
    args = parser.parse_args()

    report = audit_database(args.db_path, args.ids)
    output = Path(args.output)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "completed",
        "read_only": report["read_only"],
        "database_mutated": report["database_mutated"],
        "objects_scanned": report["objects_scanned"],
        "columns_scanned": report["columns_scanned"],
        "matching_columns": report["matching_columns"],
        "report_path": str(output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
