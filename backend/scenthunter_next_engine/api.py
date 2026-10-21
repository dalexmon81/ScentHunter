"""Opt-in FastAPI adapter for the isolated Next Engine and safe migration.

The migration API uses the same read-only snapshot exporter, pairing plan,
preflight, and importer as the CLI. It never writes to the legacy database.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time
from threading import Lock, Thread
from typing import Any

from .migration import import_legacy_snapshot
from .migration_plan import build_entries, preflight_entries, snapshot_digest
from .repository import SQLiteOfferRepository
from .search import SearchRequest, SearchService
from .sqlite_export import export_catalog
from .telemetry import metrics

try:
    from fastapi import APIRouter, Header, HTTPException, Query
except ImportError:  # Keep core package importable without FastAPI installed.
    APIRouter = None


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_snapshot(legacy_path: Path) -> dict[str, Any]:
    """Export one complete immutable-format snapshot from a read-only SQLite handle."""
    fd, name = tempfile.mkstemp(prefix="scenthunter-legacy-snapshot-", suffix=".json")
    os.close(fd)
    snapshot_path = Path(name)
    try:
        snapshot = export_catalog(legacy_path, snapshot_path, limit_per_table=500000)
        for table, data in snapshot.get("tables", {}).items():
            if isinstance(data, dict) and data.get("truncated"):
                raise HTTPException(status_code=409, detail=f"Legacy snapshot is truncated at table {table}; no import performed.")
        tables = snapshot.get("tables", {})
        product_table = tables.get("store_products", {})
        variant_table = tables.get("store_product_variants", {})
        if not isinstance(product_table, dict) or product_table.get("present") is not True:
            raise HTTPException(status_code=409, detail="Legacy table store_products is missing; no import performed.")
        if not isinstance(variant_table, dict) or variant_table.get("present") is not True:
            raise HTTPException(status_code=409, detail="Legacy table store_product_variants is missing; complete migration cannot be proven.")
        return snapshot
    finally:
        try:
            snapshot_path.unlink(missing_ok=True)
        except OSError:
            pass


def _load_job(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("migration state must be an object")
    except FileNotFoundError:
        return {"status": "idle", "result": None, "error": None, "snapshot_sha256": None}
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return {"status": "interrupted", "result": None, "error": "Persisted migration state is unreadable.", "snapshot_sha256": None}
    if state.get("status") in {"preparing", "running"}:
        state.update({"status": "interrupted", "result": None,
                      "error": "Process restarted while migration was active. No automatic resume was attempted."})
        _atomic_json(path, state)
    return state


def create_router(db_path: str | Path | None = None):
    if APIRouter is None:
        raise RuntimeError("FastAPI is required to create the next-engine API router")
    if db_path is None:
        from .runtime import validated_database_path
        path = validated_database_path()
    else:
        path = Path(db_path).expanduser().resolve()
        legacy_setting = (os.environ.get("SCENTHUNTER_LEGACY_DB") or os.environ.get("SCENTHUNTER_CATALOG_DB", "")).strip()
        if legacy_setting and path == Path(legacy_setting).expanduser().resolve():
            raise RuntimeError("next-engine database must not be the legacy catalog database")

    path.parent.mkdir(parents=True, exist_ok=True)
    repository = SQLiteOfferRepository(path)
    search_service = SearchService(repository)
    router = APIRouter(prefix="/v2", tags=["next-engine"])
    migration_lock = Lock()
    job_path = path.with_name(path.name + ".migration-job.json")
    migration_job: dict[str, Any] = _load_job(job_path)

    def persist_job() -> None:
        _atomic_json(job_path, migration_job)

    def authorize(token: str | None) -> None:
        configured = os.environ.get("SCENTHUNTER_MIGRATION_TOKEN", "").strip()
        if not configured:
            raise HTTPException(status_code=503, detail="Legacy migration is disabled: SCENTHUNTER_MIGRATION_TOKEN is not configured.")
        if not token or not secrets.compare_digest(token, configured):
            raise HTTPException(status_code=401, detail="Invalid migration token.")

    def preflight() -> tuple[list[dict[str, Any]], dict[str, Any]]:
        legacy_setting = (os.environ.get("SCENTHUNTER_LEGACY_DB") or os.environ.get("SCENTHUNTER_CATALOG_DB", "")).strip()
        if not legacy_setting:
            raise HTTPException(status_code=503, detail="Legacy migration is disabled: SCENTHUNTER_CATALOG_DB is not configured.")
        legacy_path = Path(legacy_setting).expanduser().resolve()
        if legacy_path == path:
            raise HTTPException(status_code=500, detail="Legacy and next-engine database paths must differ.")
        if not legacy_path.is_file():
            raise HTTPException(status_code=503, detail="Configured legacy database file is unavailable.")

        snapshot = _read_snapshot(legacy_path)
        tables = snapshot.get("tables", {})
        product_table = tables.get("store_products", {})
        variant_table = tables.get("store_product_variants", {})
        products = product_table.get("rows", []) if isinstance(product_table, dict) else []
        variants = variant_table.get("rows", []) if isinstance(variant_table, dict) else []
        if not isinstance(products, list) or not isinstance(variants, list):
            raise HTTPException(status_code=409, detail="Legacy snapshot rows are malformed; no import performed.")
        entries, pairing, pairing_quarantine = build_entries(products, variants)
        plan = preflight_entries(entries, pairing_quarantine)
        digest = snapshot_digest(snapshot)
        report_path = path.with_name(f"{path.name}.preflight-{digest[:16]}.json")
        public_plan = {key: value for key, value in plan.items() if not key.startswith("_")}
        report_document = {
            "snapshot_sha256": digest,
            "legacy_tables": {name: {"present": data.get("present"), "rows": len(data.get("rows", [])), "truncated": data.get("truncated", False)} for name, data in tables.items() if isinstance(data, dict)},
            "pairing": pairing,
            "preflight": public_plan,
            "dispositions": plan["_dispositions"],
            "quarantine": plan["_quarantine"],
        }
        _atomic_json(report_path, report_document)
        summary = {
            "safe_to_apply": bool(plan["safe_to_apply"] and entries),
            "snapshot_sha256": digest,
            "legacy_tables": {name: len(data.get("rows", [])) for name, data in tables.items() if isinstance(data, dict)},
            "pairing": pairing,
            "preflight": public_plan,
            "target_counts_before": repository.counts(),
            "quarantine_report": str(report_path),
            "_quarantine": plan["_quarantine"],
        }
        return entries, summary

    def run_migration(entries: list[dict[str, Any]], summary: dict[str, Any]) -> None:
        stage_path: Path | None = None
        backup_path: Path | None = None
        try:
            fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.migration-", suffix=".sqlite3", dir=str(path.parent))
            os.close(fd)
            stage_path = Path(temporary_name)
            stage = SQLiteOfferRepository(stage_path)
            staged_result = import_legacy_snapshot(entries, stage)
            staged_counts = stage.counts()
            expected_observations = int(summary["preflight"].get("valid_candidates", 0))
            if (staged_result.get("rejected_count", 0) != 0 or staged_result.get("replayed", 0) != 0
                    or staged_counts.get("observations") != expected_observations
                    or staged_result.get("imported", 0) + staged_result.get("skipped_count", 0) != len(entries)):
                raise RuntimeError("Staging validation failed; no live publication attempted. "
                                   f"candidates={len(entries)}; result={staged_result!r}; counts={staged_counts!r}")

            # Flush stage journal before copying. No target writes occur before this point.
            with sqlite3.connect(str(stage_path), timeout=30) as stage_conn:
                stage_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                stage_conn.commit()
                stage_conn.execute("PRAGMA journal_mode=DELETE")
                stage_conn.commit()

            with migration_lock:
                if migration_job.get("status") != "running":
                    raise RuntimeError("Migration state changed; publication cancelled.")
                if path.exists():
                    backup_path = path.with_name(f"{path.name}.pre-migration-{time.time_ns()}.bak")
                    with sqlite3.connect(str(path), timeout=30) as live_conn:
                        live_conn.execute("PRAGMA wal_checkpoint(FULL)")
                        live_conn.commit()
                        with sqlite3.connect(str(backup_path), timeout=30) as backup_conn:
                            live_conn.backup(backup_conn)
                target_existed_before_publish = path.exists()
                try:
                    with sqlite3.connect(str(stage_path), timeout=30) as source_conn:
                        with sqlite3.connect(str(path), timeout=30) as destination_conn:
                            source_conn.backup(destination_conn)
                    published_counts = repository.counts()
                    if published_counts != staged_counts:
                        raise RuntimeError(f"Post-publication count mismatch: stage={staged_counts!r}; published={published_counts!r}")
                except Exception:
                    if backup_path and backup_path.exists():
                        with sqlite3.connect(str(backup_path), timeout=30) as backup_conn:
                            with sqlite3.connect(str(path), timeout=30) as destination_conn:
                                backup_conn.backup(destination_conn)
                    elif not target_existed_before_publish:
                        # A failed first publication has no prior database to restore.
                        # Remove the unverified target and SQLite sidecars rather than
                        # leave a database that appears usable but failed validation.
                        for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
                            try:
                                candidate.unlink(missing_ok=True)
                            except OSError:
                                pass
                    raise

                result = {
                    "snapshot_sha256": summary["snapshot_sha256"],
                    "legacy_tables": summary["legacy_tables"],
                    "pairing": summary["pairing"],
                    "processed": staged_result["processed"],
                    "imported": staged_result["imported"],
                    "replayed": staged_result["replayed"],
                    "rejected_count": 0,
                    "partial_import": False,
                    "counts": published_counts,
                    "previous_v2_backup": str(backup_path) if backup_path else None,
                    "quarantine_report": summary["quarantine_report"],
                }
                migration_job.update({"status": "completed", "result": result, "error": None,
                                      "snapshot_sha256": summary["snapshot_sha256"]})
                persist_job()
        except Exception as exc:
            with migration_lock:
                migration_job.update({"status": "failed", "result": None,
                                      "error": f"{type(exc).__name__}: {exc}",
                                      "snapshot_sha256": summary.get("snapshot_sha256")})
                persist_job()
        finally:
            if stage_path is not None:
                for candidate in (stage_path, Path(str(stage_path) + "-wal"), Path(str(stage_path) + "-shm")):
                    try:
                        candidate.unlink(missing_ok=True)
                    except OSError:
                        pass

    @router.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "engine": "next", "database": "separate", "counts": repository.counts()}

    @router.get("/metrics")
    def engine_metrics() -> dict[str, Any]:
        return {"engine": "next", **metrics.snapshot()}

    @router.get("/search")
    def search(
        q: str = Query(default="", max_length=200),
        store: str | None = Query(default=None, max_length=64),
        currency: str | None = Query(default=None, min_length=3, max_length=3),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        try:
            return search_service.search(SearchRequest(query=q, store=store, currency=currency, limit=limit))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/migration/legacy/status")
    def migration_status(migration_token: str | None = Header(default=None, alias="X-ScentHunter-Migration-Token")) -> dict[str, Any]:
        authorize(migration_token)
        with migration_lock:
            snapshot = dict(migration_job)
        return {"ok": snapshot.get("status") not in {"failed", "interrupted"}, "mode": "apply", **snapshot}

    @router.post("/migration/legacy")
    def migrate_legacy(
        mode: str = Query(default="preview", pattern="^(preview|apply)$"),
        migration_token: str | None = Header(default=None, alias="X-ScentHunter-Migration-Token"),
    ) -> dict[str, Any]:
        authorize(migration_token)
        previous_completed = None
        if mode == "apply":
            with migration_lock:
                if migration_job.get("status") in {"preparing", "running"}:
                    return {"ok": True, "mode": "apply", "status": migration_job["status"],
                            "message": "Migration already active; do not submit apply again."}
                if migration_job.get("status") == "completed":
                    previous_completed = {"snapshot_sha256": migration_job.get("snapshot_sha256"), "result": migration_job.get("result")}
                migration_job.update({"status": "preparing", "result": None, "error": None})
                persist_job()
        try:
            entries, summary = preflight()
            public_summary = {key: value for key, value in summary.items() if not key.startswith("_")}
            if not summary["safe_to_apply"]:
                if mode == "apply":
                    with migration_lock:
                        migration_job.update({"status": "failed", "result": None,
                                              "error": "Complete preflight found quarantined or invalid candidates.",
                                              "snapshot_sha256": summary["snapshot_sha256"]})
                        persist_job()
                return {"ok": False, "mode": mode,
                        "message": "Preflight classified every candidate, but unresolved records remain in quarantine. No live database was changed.",
                        **public_summary}
            if mode == "preview":
                return {"ok": True, "mode": "preview",
                        "message": "Complete preflight passed. No live database was changed.", **public_summary}
            if previous_completed and previous_completed.get("snapshot_sha256") == summary["snapshot_sha256"]:
                with migration_lock:
                    migration_job.update({"status": "completed", "result": previous_completed.get("result"), "error": None,
                                          "snapshot_sha256": summary["snapshot_sha256"]})
                    persist_job()
                    return {"ok": True, "mode": "apply", **migration_job}
            with migration_lock:
                migration_job.update({"status": "running", "result": None, "error": None,
                                      "snapshot_sha256": summary["snapshot_sha256"]})
                persist_job()
            Thread(target=run_migration, args=(entries, summary), daemon=True,
                   name="scenthunter-legacy-migration").start()
            return {"ok": True, "mode": "apply", "status": "running",
                    "snapshot_sha256": summary["snapshot_sha256"],
                    "message": "Migration accepted. Poll GET /v2/migration/legacy/status; do not submit apply again."}
        except Exception as exc:
            if mode == "apply":
                with migration_lock:
                    migration_job.update({"status": "failed", "result": None,
                                          "error": f"{type(exc).__name__}: {exc}"})
                    persist_job()
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(status_code=500, detail=f"Migration preflight failed safely: {type(exc).__name__}: {exc}") from exc

    return router
