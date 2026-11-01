"""Read-only integrity check for the isolated Phase 2 SQLite catalog."""
from __future__ import annotations
import json
import sys
from pathlib import Path
from sqlalchemy import inspect, text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.db import database_url, make_engine

EXPECTED = {"brands", "fragrances", "product_variants", "stores", "offers",
            "price_history", "match_audit", "ingestion_runs"}

def main() -> int:
    engine = make_engine()
    try:
        with engine.connect() as connection:
            journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower()
            foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
            integrity = connection.exec_driver_sql("PRAGMA integrity_check").scalar_one()
            tables = set(inspect(connection).get_table_names())
            missing = sorted(EXPECTED - tables)
            if missing:
                raise RuntimeError(f"Missing catalog tables: {missing}")
            invalid_active = connection.execute(text(
                "SELECT COUNT(*) FROM offers WHERE status = 'active' AND "
                "(price IS NULL OR url IS NULL OR length(trim(url)) = 0 OR availability IS NULL)"
            )).scalar_one()
            counts = {name: connection.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar_one()
                      for name in sorted(EXPECTED)}
        report = {"database_url": database_url(), "journal_mode": journal_mode,
                  "foreign_keys": foreign_keys, "integrity_check": integrity,
                  "tables": sorted(EXPECTED), "row_counts": counts,
                  "invalid_active_offers": invalid_active}
        print(json.dumps(report, indent=2))
        if journal_mode != "wal" or foreign_keys != 1 or integrity != "ok" or invalid_active:
            return 1
        return 0
    finally:
        engine.dispose()

if __name__ == "__main__":
    raise SystemExit(main())
