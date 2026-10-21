"""Safe CLI migration from one immutable ScentHunter legacy snapshot.

Default is a dry-run against an in-memory V2 database. --apply validates every
candidate first, builds an isolated staging database, then backs up and publishes
only a fully validated stage. It never opens or writes the legacy database.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from backend.scenthunter_next_engine.migration import import_legacy_snapshot
from backend.scenthunter_next_engine.migration_plan import build_entries, preflight_entries, snapshot_digest
from backend.scenthunter_next_engine.repository import SQLiteOfferRepository


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
    product_table = tables.get("store_products")
    variant_table = tables.get("store_product_variants")
    if not isinstance(product_table, dict) or product_table.get("present") is not True:
        raise ValueError("Snapshot has no store_products table")
    if not isinstance(variant_table, dict) or variant_table.get("present") is not True:
        raise ValueError("Snapshot has no store_product_variants table; complete migration is not provable")
    products = product_table.get("rows", [])
    variants = variant_table.get("rows", []) if isinstance(variant_table, dict) else None
    if not isinstance(products, list) or not isinstance(variants, list):
        raise ValueError("Snapshot rows must be lists")
    if not products:
        raise ValueError("No store_products rows found")
    entries, stats, pairing_quarantine = build_entries(products, variants)
    stats["pairing_quarantine"] = pairing_quarantine
    stats["snapshot_sha256"] = snapshot_digest(snapshot)
    return entries, stats


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _counts(db_path: Path) -> dict[str, int]:
    repo = SQLiteOfferRepository(db_path)
    return repo.counts()


def _publish_stage(stage_path: Path, target: Path) -> tuple[dict[str, int], str | None]:
    """Back up target, publish stage, verify, and restore backup on any failure."""
    backup: Path | None = None
    if target.exists():
        backup = target.with_name(f"{target.name}.pre-migration-{time.time_ns()}.bak")
        with sqlite3.connect(str(target), timeout=30) as live:
            live.execute("PRAGMA wal_checkpoint(FULL)")
            live.commit()
            with sqlite3.connect(str(backup), timeout=30) as backup_conn:
                live.backup(backup_conn)
    try:
        with sqlite3.connect(str(stage_path), timeout=30) as source:
            source.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            source.commit()
            source.execute("PRAGMA journal_mode=DELETE")
            source.commit()
            with sqlite3.connect(str(target), timeout=30) as destination:
                source.backup(destination)
        stage_counts = _counts(stage_path)
        published_counts = _counts(target)
        if published_counts != stage_counts:
            raise RuntimeError(f"published counts differ from stage: stage={stage_counts}; target={published_counts}")
        return published_counts, str(backup) if backup else None
    except Exception:
        if backup and backup.exists():
            with sqlite3.connect(str(backup), timeout=30) as source:
                with sqlite3.connect(str(target), timeout=30) as destination:
                    source.backup(destination)
        else:
            # A first-time target has no prior state to restore; remove the failed
            # publication rather than leave an unverifiable database behind.
            for candidate in (target, Path(str(target) + "-wal"), Path(str(target) + "-shm")):
                try:
                    candidate.unlink(missing_ok=True)
                except OSError:
                    pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safely migrate a ScentHunter legacy snapshot into V2")
    parser.add_argument("--snapshot", required=True, help="Immutable JSON snapshot produced by sqlite_export")
    parser.add_argument("--target-db", help="Explicit V2 target; required with --apply")
    parser.add_argument("--apply", action="store_true", help="Stage, validate, back up and publish the V2 database")
    parser.add_argument("--report", help="Optional path for the complete preflight/quarantine report JSON")
    args = parser.parse_args(argv)

    try:
        snapshot_path = Path(args.snapshot).expanduser().resolve(strict=True)
        snapshot_bytes = snapshot_path.read_bytes()
        snapshot = json.loads(snapshot_bytes.decode("utf-8"))
        entries, pairing = rows_from_snapshot(snapshot)
        pairing_quarantine = pairing.pop("pairing_quarantine")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "stage": "snapshot_validation", "error": str(exc)}, ensure_ascii=False))
        return 2

    if args.apply and not args.target_db:
        parser.error("--target-db is required with --apply")
    if not args.apply and args.target_db:
        parser.error("--target-db is allowed only with --apply")

    plan = preflight_entries(entries, pairing_quarantine)
    public_plan = {k: v for k, v in plan.items() if not k.startswith("_")}
    public_pairing = {k: v for k, v in pairing.items() if not k.startswith("_")}
    safe = bool(plan["safe_to_apply"] and entries)
    target: Path | None = None
    legacy_setting = str(os.environ.get("SCENTHUNTER_LEGACY_DB") or os.environ.get("SCENTHUNTER_CATALOG_DB", "")).strip()
    legacy_path = Path(legacy_setting).expanduser().resolve() if legacy_setting else None
    if args.apply:
        target = Path(args.target_db).expanduser().resolve()
        if legacy_path and target == legacy_path:
            parser.error("Refusing to write to the configured legacy database")
        if target == snapshot_path:
            parser.error("Target database cannot be the snapshot file")
        if target.exists() and not target.is_file():
            parser.error("Target path exists but is not a file")

    report_path = Path(args.report).expanduser().resolve() if args.report else None
    protected_paths = {snapshot_path}
    if legacy_path:
        protected_paths.add(legacy_path)
    if target is not None:
        protected_paths.add(target)
    if report_path is not None and report_path in protected_paths:
        print(json.dumps({"ok": False, "stage": "report_path_validation",
                          "error": "Report path must differ from the snapshot, configured legacy database, and target database."}, ensure_ascii=False))
        return 2

    report = {
        "ok": safe,
        "mode": "apply" if args.apply else "dry_run",
        "snapshot": str(snapshot_path),
        "snapshot_sha256": pairing.get("snapshot_sha256"),
        "target_database": str(target) if target and args.apply else "<in-memory; no persistent writes>",
        "pairing": public_pairing,
        "preflight": public_plan,
        "dispositions": plan["_dispositions"],
        "quarantine": plan["_quarantine"],
        "legacy_database_opened": False,
        "legacy_database_written": False,
        "network_requests": 0,
    }
    if report_path is not None:
        try:
            _write_json_atomic(report_path, report)
            report["report_path"] = str(report_path)
        except OSError as exc:
            print(json.dumps({"ok": False, "stage": "report_write", "error": str(exc)}, ensure_ascii=False))
            return 2

    if not safe:
        # No repository has been opened for writes; every candidate has a disposition.
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 1

    if not args.apply:
        # Exercise the actual importer against an in-memory DB after shared preflight.
        try:
            repository = SQLiteOfferRepository(":memory:")
            result = import_legacy_snapshot(entries, repository)
            if result.get("rejected_count") or result.get("imported", 0) + result.get("skipped_count", 0) != len(entries) or result.get("replayed", 0):
                report["ok"] = False
                report["dry_run_import"] = result
                print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
                return 1
            report["dry_run_import"] = {k: v for k, v in result.items() if k != "rejected"}
            report["dry_run_import"]["target_counts"] = result.get("target_counts")
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
            return 0
        except Exception as exc:
            print(json.dumps({"ok": False, "stage": "dry_run", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
            return 2

    assert target is not None
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, stage_name = tempfile.mkstemp(prefix=f".{target.name}.stage-", suffix=".sqlite3", dir=str(target.parent))
    os.close(fd)
    stage_path = Path(stage_name)
    try:
        stage = SQLiteOfferRepository(stage_path)
        result = import_legacy_snapshot(entries, stage)
        staged_counts = stage.counts()
        expected_observations = int(plan.get("valid_candidates", 0))
        if (result.get("rejected_count") or result.get("replayed", 0) != 0
                or result.get("imported", 0) + result.get("skipped_count", 0) != len(entries)
                or staged_counts.get("observations") != expected_observations):
            report.update({"ok": False, "stage": "staging_validation", "staging_import": result, "staging_counts": staged_counts})
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
            return 1
        published_counts, backup_path = _publish_stage(stage_path, target)
        report.update({"ok": True, "staging_counts": staged_counts, "published_counts": published_counts,
                       "previous_target_backup": backup_path, "staging_import": {k: v for k, v in result.items() if k != "rejected"}})
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "stage": "apply", "error": f"{type(exc).__name__}: {exc}",
                          "target_database": str(target), "rollback_backup_retained": True}, ensure_ascii=False))
        return 2
    finally:
        for candidate in (stage_path, Path(str(stage_path) + "-wal"), Path(str(stage_path) + "-shm")):
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
