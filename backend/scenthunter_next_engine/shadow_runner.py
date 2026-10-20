"""Offline shadow-comparison runner. Reads JSON snapshots and writes a report only.

This module deliberately does not connect to the production catalog DB and does
not call retailer/network code. Input rows must be exported explicitly.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .shadow import compare_search_results


def _load_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        if isinstance(payload.get("rows"), list):
            payload = payload["rows"]
        elif isinstance(payload.get("tables"), dict):
            tables = payload["tables"]
            table = tables.get("store_product_variants") or tables.get("store_products") or {}
            payload = table.get("rows") if isinstance(table, dict) else None
        else:
            payload = None
    if not isinstance(payload, list):
        raise ValueError(f"{path}: expected a JSON array, an object with a 'rows' array, or a schema-aware SQLite export")
    if any(not isinstance(row, dict) for row in payload):
        raise ValueError(f"{path}: every row must be a JSON object")
    return payload


def run_shadow(legacy_path: str | Path, next_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    """Compare two pre-exported JSON snapshots and save a deterministic report."""
    legacy_file, next_file, output_file = map(Path, (legacy_path, next_path, output_path))
    if legacy_file.resolve() == next_file.resolve():
        raise ValueError("legacy and next inputs must be different files")
    if output_file.resolve() in {legacy_file.resolve(), next_file.resolve()}:
        raise ValueError("report output must not overwrite either input snapshot")

    report = {
        "schema_version": 1,
        "mode": "offline_snapshot_only",
        "mutated_database": False,
        "network_requests": 0,
        "comparison": compare_search_results(_load_rows(legacy_file), _load_rows(next_file)),
    }
    output_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_file.with_suffix(output_file.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, output_file)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare pre-exported ScentHunter catalog snapshots safely")
    parser.add_argument("--legacy", required=True, help="Path to legacy JSON snapshot")
    parser.add_argument("--next", required=True, help="Path to next-engine JSON snapshot")
    parser.add_argument("--output", required=True, help="Path for the JSON report (must differ from inputs)")
    args = parser.parse_args(argv)
    try:
        report = run_shadow(args.legacy, args.next, args.output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    summary = report["comparison"]
    print(json.dumps({"report": str(Path(args.output)), "mode": report["mode"], **{
        key: summary[key] for key in ("legacy_count", "next_count", "matched_count", "legacy_only_count", "next_only_count", "price_difference_count", "currency_mismatch_count", "url_difference_count")
    }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
