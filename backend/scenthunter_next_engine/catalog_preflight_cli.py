"""Run the read-only catalog preflight against the repository catalog.

Usage from the repository root:
    python -m backend.scenthunter_next_engine.catalog_preflight_cli

This command reads backend/product_catalog.json and prints a JSON report.
It never writes to the catalog, database, or filesystem.
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.scenthunter_next_engine.catalog_preflight import audit_catalog_data


def main() -> int:
    repository_root = Path(__file__).resolve().parents[2]
    catalog_path = repository_root / "backend" / "product_catalog.json"

    try:
        with catalog_path.open("r", encoding="utf-8") as catalog_file:
            catalog_data = json.load(catalog_file)
        report = audit_catalog_data(catalog_data)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({
            "status": "error",
            "catalog_path": str(catalog_path),
            "error": str(exc),
            "read_only": True,
        }, ensure_ascii=False, indent=2))
        return 2

    report["status"] = "complete"
    report["catalog_path"] = str(catalog_path)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    # Findings are reported for review; this command does not modify or block
    # the repository and does not claim that a migration is approved.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
