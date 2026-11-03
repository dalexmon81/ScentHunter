"""Strictly read-only Phase 2 production SQLite diagnostic."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import quote

RAW_ID = "b9a5a0e9-2130-4dfa-b016-e717071235a1"
OFFER_ID = "f723da10-5f85-4c8e-93bf-c0072163e88e"
SKU = "614514178065"

def main() -> int:
    raw_url = (os.environ.get("SCENTHUNTER_CATALOG_DATABASE_URL")
               or os.environ.get("SCENTHUNTER_DATABASE_URL")
               or "sqlite:////data/catalog/catalog.sqlite3").strip()
    if not raw_url.startswith("sqlite:"):
        raise RuntimeError("Configured Phase 2 database is not SQLite; refusing to continue.")
    database = raw_url.removeprefix("sqlite:///")
    if database == ":memory:" or not database:
        raise RuntimeError("Configured database path is not a persistent SQLite file.")
    path = Path("/" + database.lstrip("/")) if raw_url.startswith("sqlite:////") else Path(database)
    path = path.expanduser().resolve()
    if not path.is_file():
        print(json.dumps({"database_path": "<masked>", "database_file_exists": False}))
        return 2

    uri = "file:" + quote(str(path), safe="/") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only=ON")
        con.execute("PRAGMA busy_timeout=10000")
        tables = {r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        result = {
            "database_path": ".../" + path.name,
            "database_file_exists": True,
            "connection_mode": "SQLite mode=ro; query_only=ON",
            "runtime_config_source": (
                "SCENTHUNTER_CATALOG_DATABASE_URL"
                if os.environ.get("SCENTHUNTER_CATALOG_DATABASE_URL")
                else "SCENTHUNTER_DATABASE_URL"
                if os.environ.get("SCENTHUNTER_DATABASE_URL")
                else "application default"
            ),
            "offers_columns": [],
            "ingestion_raw_columns": [],
            "ingestion_raw_total": None,
            "target_raw": [],
            "target_offer": [],
            "sku_payload_matches": None,
            "offers_linked_to_target_raw": [],
        }
        for table, key in (("offers", "offers_columns"),
                           ("ingestion_raw", "ingestion_raw_columns")):
            if table in tables:
                result[key] = [
                    {"name": row["name"], "type": row["type"]}
                    for row in con.execute(f"PRAGMA table_info({table})")
                ]
        if "ingestion_raw" in tables:
            result["ingestion_raw_total"] = con.execute(
                "SELECT COUNT(*) FROM ingestion_raw"
            ).fetchone()[0]
            result["target_raw"] = [
                dict(row) for row in con.execute(
                    "SELECT id, status, created_at FROM ingestion_raw WHERE id = ?",
                    (RAW_ID,)
                ).fetchall()
            ]
            result["sku_payload_matches"] = con.execute(
                "SELECT COUNT(*) FROM ingestion_raw WHERE raw_payload LIKE ?",
                (f"%{SKU}%",)
            ).fetchone()[0]
        if "offers" in tables:
            result["target_offer"] = [
                dict(row) for row in con.execute(
                    "SELECT id, ingestion_raw_id, status, product_variant_id, captured_at "
                    "FROM offers WHERE id = ?", (OFFER_ID,)
                ).fetchall()
            ]
            result["offers_linked_to_target_raw"] = [
                dict(row) for row in con.execute(
                    "SELECT id, ingestion_raw_id, status, product_variant_id, captured_at "
                    "FROM offers WHERE ingestion_raw_id = ?", (RAW_ID,)
                ).fetchall()
            ]
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    finally:
        con.close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
