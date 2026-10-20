"""Safe, explicit importer for a sqlite_export.py JSON snapshot.

Default mode is DRY RUN: validates/mapping in an in-memory V2 database.
Use --apply and an explicit --target-db path to persist to V2 only.
Never opens or writes the legacy SQLite database and makes no network calls.
Run from repository root so backend.scenthunter_next_engine is importable.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from backend.scenthunter_next_engine.migration import import_legacy_snapshot
from backend.scenthunter_next_engine.repository import SQLiteOfferRepository


def norm_store(value: Any) -> str:
    return str(value or "").strip().casefold()


def norm_url(value: Any) -> str:
    # Deliberately exact after trimming: no fuzzy URL/product matching.
    return str(value or "").strip()


def rows_from_snapshot(snapshot: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if snapshot.get("schema_version") != 1:
        raise ValueError(f"unsupported snapshot schema_version: {snapshot.get('schema_version')!r}")
    if snapshot.get("source") != "scenthunter_legacy_sqlite" or snapshot.get("read_only") is not True:
        raise ValueError("file is not a recognized read-only legacy snapshot")

    tables = snapshot.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("snapshot.tables must be an object")

    for name, data in tables.items():
        if isinstance(data, dict) and data.get("truncated") is True:
            raise ValueError(f"snapshot table {name!r} is truncated; export again with a higher limit")

    products_data = tables.get("store_products", {})
    variants_data = tables.get("store_product_variants", {})
    products = products_data.get("rows", []) if isinstance(products_data, dict) else []
    variants = variants_data.get("rows", []) if isinstance(variants_data, dict) else []
    if not isinstance(products, list) or not isinstance(variants, list):
        raise ValueError("snapshot table rows must be lists")
    if not products:
        raise ValueError("snapshot contains no store_products rows; nothing safe to migrate")

    # Exact composite key only. Duplicate base rows remain separate candidates
    # and are counted; variant rows are attached only if exactly one base row
    # matches the same normalized store + exact URL.
    bases: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in products:
        if not isinstance(row, dict):
            continue
        key = (norm_store(row.get("store")), norm_url(row.get("url")))
        if key[0] and key[1]:
            bases[key].append(row)

    variants_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in variants:
        if not isinstance(row, dict):
            continue
        key = (norm_store(row.get("store")), norm_url(row.get("url")))
        if key[0] and key[1]:
            variants_by_key[key].append(row)

    entries: list[dict[str, Any]] = []
    paired_variant_rows = 0
    orphan_variant_rows = 0
    ambiguous_variant_rows = 0
    base_rows_without_key = 0
    base_rows_with_variants = 0

    for row in products:
        if not isinstance(row, dict):
            base_rows_without_key += 1
            continue
        store = norm_store(row.get("store"))
        url = norm_url(row.get("url"))
        if not store or not url:
            base_rows_without_key += 1
            # Keep it in the candidate stream so importer reports a clear rejection.
            entries.append({"store": store, "product_row": row, "variant_row": None})
            continue
        key = (store, url)
        matching_bases = bases.get(key, [])
        if len(matching_bases) != 1:
            # Avoid duplicating or attaching variants to an ambiguous base row.
            entries.append({"store": store, "product_row": row, "variant_row": None})
            continue
        matching_variants = variants_by_key.get(key, [])
        if matching_variants:
            base_rows_with_variants += 1
            for variant in matching_variants:
                entries.append({"store": store, "product_row": row, "variant_row": variant})
                paired_variant_rows += 1
        else:
            entries.append({"store": store, "product_row": row, "variant_row": None})

    # Variant rows with no unique matching base are not imported: importer
    # requires a trustworthy parent product row, so count them for the report.
    for key, group in variants_by_key.items():
        if len(bases.get(key, [])) == 0:
            orphan_variant_rows += len(group)
        elif len(bases.get(key, [])) > 1:
            ambiguous_variant_rows += len(group)

    stats = {
        "snapshot_products_rows": len(products),
        "snapshot_variant_rows": len(variants),
        "candidate_observations": len(entries),
        "paired_variant_rows": paired_variant_rows,
        "base_rows_with_variants": base_rows_with_variants,
        "orphan_variant_rows_not_imported": orphan_variant_rows,
        "ambiguous_variant_rows_not_imported": ambiguous_variant_rows,
        "base_rows_missing_store_or_url": base_rows_without_key,
    }
    return entries, stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely import a legacy snapshot into ScentHunter V2")
    parser.add_argument("--snapshot", required=True, help="JSON file created by sqlite_export.py")
    parser.add_argument("--target-db", help="V2 SQLite destination; required with --apply")
    parser.add_argument("--apply", action="store_true", help="Persist into the explicitly supplied V2 database")
    args = parser.parse_args()

    snapshot_path = Path(args.snapshot).expanduser().resolve(strict=True)
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        entries, pairing_stats = rows_from_snapshot(snapshot)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "stage": "snapshot_validation", "error": str(exc)}, ensure_ascii=False))
        return 2

    if args.apply and not args.target_db:
        parser.error("--target-db is required when --apply is set")
    if not args.apply and args.target_db:
        parser.error("--target-db is only accepted with --apply; dry-run always uses in-memory SQLite")

    if args.apply:
        target = Path(args.target_db).expanduser().resolve()
        legacy = str(os.environ.get("SCENTHUNTER_LEGACY_DB") or os.environ.get("SCENTHUNTER_CATALOG_DB", "")).strip()
        if legacy and target == Path(legacy).expanduser().resolve():
            print(json.dumps({"ok": False, "stage": "target_validation", "error": "target database equals configured legacy database; refusing to write"}))
            return 2
        if target == snapshot_path:
            print(json.dumps({"ok": False, "stage": "target_validation", "error": "target database path equals snapshot path; refusing"}))
            return 2
        if target.exists() and not target.is_file():
            print(json.dumps({"ok": False, "stage": "target_validation", "error": "target path exists but is not a file"}))
            return 2
        target.parent.mkdir(parents=True, exist_ok=True)
        target_db = str(target)
    else:
        target_db = ":memory:"

    try:
        repository = SQLiteOfferRepository(target_db)
        result = import_legacy_snapshot(entries, repository)
        output = {
            "ok": result.get("rejected_count", 0) == 0 and pairing_stats["orphan_variant_rows_not_imported"] == 0 and pairing_stats["ambiguous_variant_rows_not_imported"] == 0,
            "mode": "apply" if args.apply else "dry_run",
            "snapshot": str(snapshot_path),
            "target_database": target_db if args.apply else "<in-memory; no persistent writes>",
            "pairing": pairing_stats,
            "import": result,
            "legacy_database_opened": False,
            "legacy_database_written": False,
            "network_requests": 0,
            "product_catalog_json_touched": False,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
        return 0 if output["ok"] else 1
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
        print(json.dumps({"ok": False, "stage": "import", "mode": "apply" if args.apply else "dry_run", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
