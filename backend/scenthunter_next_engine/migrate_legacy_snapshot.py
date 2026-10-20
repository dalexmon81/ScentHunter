"""Safe importer for a ScentHunter legacy SQLite JSON snapshot.

Default: dry-run using an in-memory V2 database.
--apply: writes only to the explicitly specified V2 database.
Never opens the legacy SQLite database or makes network requests.
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
    return str(value or "").strip()


def rows_from_snapshot(snapshot: dict[str, Any]):
    if snapshot.get("schema_version") != 1:
        raise ValueError("Unsupported snapshot schema_version")
    if snapshot.get("source") != "scenthunter_legacy_sqlite":
        raise ValueError("Not a ScentHunter legacy snapshot")
    if snapshot.get("read_only") is not True:
        raise ValueError("Snapshot is not marked read-only")

    tables = snapshot.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("snapshot.tables must be an object")

    for name, data in tables.items():
        if isinstance(data, dict) and data.get("truncated") is True:
            raise ValueError(f"Table {name} is truncated; export it again")

    product_table = tables.get("store_products", {})
    variant_table = tables.get("store_product_variants", {})
    products = product_table.get("rows", []) if isinstance(product_table, dict) else []
    variants = variant_table.get("rows", []) if isinstance(variant_table, dict) else []

    if not isinstance(products, list) or not isinstance(variants, list):
        raise ValueError("Snapshot rows must be lists")
    if not products:
        raise ValueError("No store_products rows found")

    bases = defaultdict(list)
    variants_by_key = defaultdict(list)

    for row in products:
        if isinstance(row, dict):
            key = (norm_store(row.get("store")), norm_url(row.get("url")))
            if all(key):
                bases[key].append(row)

    for row in variants:
        if isinstance(row, dict):
            key = (norm_store(row.get("store")), norm_url(row.get("url")))
            if all(key):
                variants_by_key[key].append(row)

    entries = []
    paired = orphan = ambiguous = missing_key = 0

    for row in products:
        if not isinstance(row, dict):
            missing_key += 1
            continue

        store = norm_store(row.get("store"))
        url = norm_url(row.get("url"))

        if not store or not url:
            missing_key += 1
            entries.append({
                "store": store,
                "product_row": row,
                "variant_row": None,
            })
            continue

        key = (store, url)
        if len(bases[key]) != 1:
            entries.append({
                "store": store,
                "product_row": row,
                "variant_row": None,
            })
            continue

        matches = variants_by_key.get(key, [])
        if matches:
            for variant in matches:
                entries.append({
                    "store": store,
                    "product_row": row,
                    "variant_row": variant,
                })
                paired += 1
        else:
            entries.append({
                "store": store,
                "product_row": row,
                "variant_row": None,
            })

    for key, group in variants_by_key.items():
        if len(bases.get(key, [])) == 0:
            orphan += len(group)
        elif len(bases[key]) > 1:
            ambiguous += len(group)

    stats = {
        "products_rows": len(products),
        "variant_rows": len(variants),
        "candidate_observations": len(entries),
        "paired_variants": paired,
        "orphan_variants_not_imported": orphan,
        "ambiguous_variants_not_imported": ambiguous,
        "base_rows_missing_store_or_url": missing_key,
    }
    return entries, stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely migrate a ScentHunter legacy snapshot into V2"
    )
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--target-db")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    try:
        snapshot_path = Path(args.snapshot).expanduser().resolve(strict=True)
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        entries, pairing = rows_from_snapshot(snapshot)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({
            "ok": False,
            "stage": "snapshot_validation",
            "error": str(exc),
        }, ensure_ascii=False))
        return 2

    if args.apply and not args.target_db:
        parser.error("--target-db is required with --apply")
    if not args.apply and args.target_db:
        parser.error("--target-db is allowed only with --apply")

    if args.apply:
        target = Path(args.target_db).expanduser().resolve()
        legacy = str(
            os.environ.get("SCENTHUNTER_LEGACY_DB")
            or os.environ.get("SCENTHUNTER_CATALOG_DB", "")
        ).strip()

        if legacy and target == Path(legacy).expanduser().resolve():
            parser.error("Refusing to write to the legacy database")
        if target == snapshot_path:
            parser.error("Target database cannot be the snapshot file")
        if target.exists() and not target.is_file():
            parser.error("Target path exists but is not a file")

        target.parent.mkdir(parents=True, exist_ok=True)
        target_db = str(target)
    else:
        target_db = ":memory:"

    try:
        repository = SQLiteOfferRepository(target_db)
        result = import_legacy_snapshot(entries, repository)

        safe = (
            result.get("rejected_count", 0) == 0
            and pairing["orphan_variants_not_imported"] == 0
            and pairing["ambiguous_variants_not_imported"] == 0
        )

        print(json.dumps({
            "ok": safe,
            "mode": "apply" if args.apply else "dry_run",
            "target_database": (
                target_db if args.apply
                else "<in-memory; no persistent writes>"
            ),
            "pairing": pairing,
            "import": result,
            "legacy_database_opened": False,
            "legacy_database_written": False,
            "network_requests": 0,
            "product_catalog_json_touched": False,
        }, ensure_ascii=False, indent=2, default=str))

        return 0 if safe else 1

    except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
        print(json.dumps({
            "ok": False,
            "stage": "import",
            "mode": "apply" if args.apply else "dry_run",
            "error": f"{type(exc).__name__}: {exc}",
        }, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
