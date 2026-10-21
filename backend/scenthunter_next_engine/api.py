"""FastAPI adapter for ScentHunter Next Engine and safe legacy migration."""
from __future__ import annotations
import json, os, secrets, sqlite3, tempfile, time
from pathlib import Path
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
except ImportError:
    APIRouter = None


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _load_job(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
        try:
            state = json.loads(raw)
        except json.JSONDecodeError:
            # Compatibility with files written by the previous buggy serializer,
            # which appended the two literal characters backslash+n.
            if raw.endswith("\\n"):
                state = json.loads(raw[:-2])
            else:
                raise
        if not isinstance(state, dict):
            raise ValueError("state must be an object")
    except FileNotFoundError:
        return {"status": "idle", "result": None, "error": None, "snapshot_sha256": None}
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return {"status": "interrupted", "result": None, "error": "Persisted state is unreadable.", "snapshot_sha256": None}
    if state.get("status") in {"queued", "preparing", "running"}:
        state.update(status="interrupted", result=None,
                     error="Process restarted while work was active; it was not resumed automatically.")
        _atomic_json(path, state)
    return state


def _read_snapshot(legacy_path: Path) -> dict[str, Any]:
    fd, name = tempfile.mkstemp(prefix="scenthunter-legacy-snapshot-", suffix=".json")
    os.close(fd)
    tmp = Path(name)
    try:
        snapshot = export_catalog(legacy_path, tmp, limit_per_table=500000)
        tables = snapshot.get("tables", {})
        for table, data in tables.items():
            if isinstance(data, dict) and data.get("truncated"):
                raise HTTPException(status_code=409, detail=f"Legacy snapshot truncated at {table}; no import performed.")
        for name in ("store_products", "store_product_variants"):
            data = tables.get(name, {})
            if not isinstance(data, dict) or data.get("present") is not True:
                raise HTTPException(status_code=409, detail=f"Legacy table {name} is missing; complete migration cannot be proven.")
        return snapshot
    finally:
        try: tmp.unlink(missing_ok=True)
        except OSError: pass


def create_router(db_path: str | Path | None = None):
    if APIRouter is None:
        raise RuntimeError("FastAPI is required")
    if db_path is None:
        from .runtime import validated_database_path
        path = validated_database_path()
    else:
        path = Path(db_path).expanduser().resolve()
        legacy = (os.environ.get("SCENTHUNTER_LEGACY_DB") or os.environ.get("SCENTHUNTER_CATALOG_DB", "")).strip()
        if legacy and path == Path(legacy).expanduser().resolve():
            raise RuntimeError("next-engine database must not be the legacy catalog database")

    path.parent.mkdir(parents=True, exist_ok=True)
    repository = SQLiteOfferRepository(path)
    search_service = SearchService(repository)
    router = APIRouter(prefix="/v2", tags=["next-engine"])

    apply_lock, preview_lock = Lock(), Lock()
    apply_path = path.with_name(path.name + ".migration-job.json")
    preview_path = path.with_name(path.name + ".preview-job.json")
    apply_job, preview_job = _load_job(apply_path), _load_job(preview_path)

    def authorize(token: str | None) -> None:
        configured = os.environ.get("SCENTHUNTER_MIGRATION_TOKEN", "").strip()
        if not configured:
            raise HTTPException(503, "Legacy migration is disabled: SCENTHUNTER_MIGRATION_TOKEN is not configured.")
        if not token or not secrets.compare_digest(token, configured):
            raise HTTPException(401, "Invalid migration token.")

    def persist(path_: Path, lock: Lock, job: dict[str, Any]) -> None:
        with lock:
            _atomic_json(path_, job)

    def preflight():
        legacy_setting = (os.environ.get("SCENTHUNTER_LEGACY_DB") or os.environ.get("SCENTHUNTER_CATALOG_DB", "")).strip()
        if not legacy_setting:
            raise HTTPException(503, "Legacy migration is disabled: SCENTHUNTER_CATALOG_DB is not configured.")
        legacy_path = Path(legacy_setting).expanduser().resolve()
        if legacy_path == path:
            raise HTTPException(500, "Legacy and next-engine database paths must differ.")
        if not legacy_path.is_file():
            raise HTTPException(503, "Configured legacy database file is unavailable.")
        snapshot = _read_snapshot(legacy_path)
        tables = snapshot.get("tables", {})
        products = tables["store_products"].get("rows", [])
        variants = tables["store_product_variants"].get("rows", [])
        if not isinstance(products, list) or not isinstance(variants, list):
            raise HTTPException(409, "Legacy snapshot rows are malformed; no import performed.")
        entries, pairing, pairing_quarantine = build_entries(products, variants)
        plan = preflight_entries(entries, pairing_quarantine)
        digest = snapshot_digest(snapshot)
        report = path.with_name(f"{path.name}.preflight-{digest[:16]}.json")
        public_plan = {k: v for k, v in plan.items() if not k.startswith("_")}
        tables_summary = {n: len(d.get("rows", [])) for n, d in tables.items() if isinstance(d, dict)}
        quarantine_rows = plan["_quarantine"]
        def aggregate_quarantine(field: str) -> list[dict[str, Any]]:
            counts: dict[str, int] = {}
            for item in quarantine_rows:
                value = item.get(field) if isinstance(item, dict) else None
                key = str(value).strip() if value not in (None, "") else "unknown"
                counts[key] = counts.get(key, 0) + 1
            return [{"value": key, "count": count}
                    for key, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))]
        quarantine_summary = {
            "total": len(quarantine_rows),
            "by_class": aggregate_quarantine("class"),
            "by_reason": aggregate_quarantine("reason"),
            "by_store": aggregate_quarantine("store"),
        }
        # Persist aggregate diagnostics only. Storing every quarantined row in
        # a pretty-printed JSON report can exhaust the persistent Fly volume.
        _atomic_json(report, {
            "snapshot_sha256": digest,
            "legacy_tables": {n: {"present": d.get("present"), "rows": len(d.get("rows", [])), "truncated": d.get("truncated", False)} for n, d in tables.items() if isinstance(d, dict)},
            "pairing": pairing, "preflight": public_plan,
            "dispositions": plan["_dispositions"],
            "quarantine_summary": quarantine_summary,
        })
        summary = {
            "safe_to_apply": bool(plan["safe_to_apply"] and entries),
            "snapshot_sha256": digest, "legacy_tables": tables_summary,
            "pairing": pairing, "preflight": public_plan,
            "target_counts_before": repository.counts(),
            "quarantine_report": str(report),
        }
        return entries, summary

    def run_preview():
        try:
            _, summary = preflight()
            public = {k: v for k, v in summary.items() if not k.startswith("_")}
            result = {
                "ok": bool(summary["safe_to_apply"]), "mode": "preview",
                "message": ("Complete preflight passed. No live database was changed."
                            if summary["safe_to_apply"] else
                            "Preflight completed with unresolved records. No live database was changed."),
                **public,
            }
            state = {"status": "completed", "result": result, "error": None,
                     "snapshot_sha256": summary["snapshot_sha256"]}
        except Exception as exc:
            state = {"status": "failed", "result": None,
                     "error": f"{type(exc).__name__}: {exc}", "snapshot_sha256": None}
        with preview_lock:
            preview_job.clear()
            preview_job.update(state)
            _atomic_json(preview_path, preview_job)

    def run_migration(entries, summary):
        stage_path = backup_path = None
        try:
            fd, name = tempfile.mkstemp(prefix=f".{path.name}.migration-", suffix=".sqlite3", dir=str(path.parent))
            os.close(fd)
            stage_path = Path(name)
            stage = SQLiteOfferRepository(stage_path)
            result = import_legacy_snapshot(entries, stage)
            counts = stage.counts()
            expected = int(summary["preflight"].get("valid_candidates", 0))
            if (result.get("rejected_count", 0) or result.get("replayed", 0)
                or counts.get("observations") != expected
                or result.get("imported", 0) + result.get("skipped_count", 0) != len(entries)):
                raise RuntimeError(f"Staging validation failed; no live publication attempted. candidates={len(entries)}; result={result!r}; counts={counts!r}")
            with sqlite3.connect(str(stage_path), timeout=30) as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)"); conn.commit()
                conn.execute("PRAGMA journal_mode=DELETE"); conn.commit()
            with apply_lock:
                if apply_job.get("status") != "running":
                    raise RuntimeError("Migration state changed; publication cancelled.")
                if path.exists():
                    backup_path = path.with_name(f"{path.name}.pre-migration-{time.time_ns()}.bak")
                    with sqlite3.connect(str(path), timeout=30) as live, sqlite3.connect(str(backup_path), timeout=30) as backup:
                        live.execute("PRAGMA wal_checkpoint(FULL)"); live.commit(); live.backup(backup)
                existed = path.exists()
                try:
                    with sqlite3.connect(str(stage_path), timeout=30) as src, sqlite3.connect(str(path), timeout=30) as dst:
                        src.backup(dst)
                    published = repository.counts()
                    if published != counts:
                        raise RuntimeError(f"Post-publication count mismatch: stage={counts!r}; published={published!r}")
                except Exception:
                    if backup_path and backup_path.exists():
                        with sqlite3.connect(str(backup_path), timeout=30) as src, sqlite3.connect(str(path), timeout=30) as dst: src.backup(dst)
                    elif not existed:
                        for p in (path, Path(str(path)+"-wal"), Path(str(path)+"-shm")):
                            try: p.unlink(missing_ok=True)
                            except OSError: pass
                    raise
                final = {
                    "snapshot_sha256": summary["snapshot_sha256"], "legacy_tables": summary["legacy_tables"],
                    "pairing": summary["pairing"], "processed": result["processed"],
                    "imported": result["imported"], "replayed": result["replayed"],
                    "rejected_count": 0, "partial_import": False, "counts": published,
                    "previous_v2_backup": str(backup_path) if backup_path else None,
                    "quarantine_report": summary["quarantine_report"],
                }
                apply_job.update(status="completed", result=final, error=None, snapshot_sha256=summary["snapshot_sha256"])
                _atomic_json(apply_path, apply_job)
        except Exception as exc:
            with apply_lock:
                apply_job.update(status="failed", result=None, error=f"{type(exc).__name__}: {exc}",
                                 snapshot_sha256=summary.get("snapshot_sha256"))
                _atomic_json(apply_path, apply_job)
        finally:
            if stage_path:
                for p in (stage_path, Path(str(stage_path)+"-wal"), Path(str(stage_path)+"-shm")):
                    try: p.unlink(missing_ok=True)
                    except OSError: pass

    @router.get("/health")
    def health():
        return {"ok": True, "engine": "next", "database": "separate", "counts": repository.counts()}

    @router.get("/metrics")
    def engine_metrics():
        return {"engine": "next", **metrics.snapshot()}

    @router.get("/search")
    def search(q: str = Query(default="", max_length=200),
               store: str | None = Query(default=None, max_length=64),
               currency: str | None = Query(default=None, min_length=3, max_length=3),
               limit: int = Query(default=50, ge=1, le=200)):
        try:
            return search_service.search(SearchRequest(query=q, store=store, currency=currency, limit=limit))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/migration/legacy/quarantine-summary")
    def migration_quarantine_summary(
        migration_token: str | None = Header(default=None, alias="X-ScentHunter-Migration-Token"),
    ) -> dict[str, Any]:
        """Read aggregate quarantine diagnostics from the latest preview report.

        This endpoint is read-only: it does not rerun preflight or touch either database.
        """
        authorize(migration_token)
        with preview_lock:
            state = dict(preview_job)
        if state.get("status") != "completed" or not isinstance(state.get("result"), dict):
            raise HTTPException(409, "No completed preview report is available. Run preview first.")
        report_value = state["result"].get("quarantine_report")
        if not report_value:
            raise HTTPException(404, "The completed preview does not reference a quarantine report.")
        report_path = Path(str(report_value)).expanduser().resolve()
        expected_prefix = path.name + ".preflight-"
        if report_path.parent != path.parent or not report_path.name.startswith(expected_prefix):
            raise HTTPException(403, "Quarantine report path is outside the expected report directory.")
        try:
            raw = report_path.read_text(encoding="utf-8")
            try:
                report_data = json.loads(raw)
            except json.JSONDecodeError:
                # Also read reports created before the serializer newline fix.
                if raw.endswith("\\n"):
                    report_data = json.loads(raw[:-2])
                else:
                    raise
        except FileNotFoundError as exc:
            raise HTTPException(404, "Quarantine report file is missing from the service volume.") from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise HTTPException(500, "Quarantine report exists but is not valid JSON.") from exc

        saved_summary = report_data.get("quarantine_summary")
        if isinstance(saved_summary, dict):
            quarantine_total = int(saved_summary.get("total", 0))
            by_class = saved_summary.get("by_class", [])
            by_reason = saved_summary.get("by_reason", [])
            by_store = saved_summary.get("by_store", [])
        else:
            # Backward compatibility with reports created before aggregate-only
            # persistence was introduced.
            quarantine = report_data.get("quarantine", [])
            if not isinstance(quarantine, list):
                raise HTTPException(500, "Quarantine report has an invalid quarantine section.")
            def count_field(field: str) -> list[dict[str, Any]]:
                counts: dict[str, int] = {}
                for item in quarantine:
                    value = item.get(field) if isinstance(item, dict) else None
                    key = str(value).strip() if value not in (None, "") else "unknown"
                    counts[key] = counts.get(key, 0) + 1
                return [{"value": key, "count": count} for key, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))]
            quarantine_total = len(quarantine)
            by_class = count_field("class")
            by_reason = count_field("reason")
            by_store = count_field("store")

        return {
            "ok": True,
            "mode": "preview",
            "snapshot_sha256": report_data.get("snapshot_sha256"),
            "quarantine_total": quarantine_total,
            "by_class": by_class,
            "by_reason": by_reason,
            "by_store": by_store,
            "message": "Read-only aggregate of the existing preview report; no migration or database writes were performed.",
        }

    @router.get("/migration/legacy/status")
    def migration_status(mode: str = Query(default="preview", pattern="^(preview|apply)$"),
                         migration_token: str | None = Header(default=None, alias="X-ScentHunter-Migration-Token")):
        authorize(migration_token)
        lock, job = (preview_lock, preview_job) if mode == "preview" else (apply_lock, apply_job)
        with lock: snapshot = dict(job)
        return {"ok": snapshot.get("status") not in {"failed", "interrupted"}, "mode": mode, **snapshot}

    @router.post("/migration/legacy")
    def migrate_legacy(mode: str = Query(default="preview", pattern="^(preview|apply)$"),
                       migration_token: str | None = Header(default=None, alias="X-ScentHunter-Migration-Token")):
        authorize(migration_token)
        if mode == "preview":
            with preview_lock:
                if preview_job.get("status") in {"queued", "running"}:
                    return {"ok": True, "mode": "preview", "status": preview_job["status"],
                            "message": "Preview already active; poll GET /v2/migration/legacy/status?mode=preview."}
                preview_job.clear()
                preview_job.update(status="running", result=None, error=None, snapshot_sha256=None, started_at=time.time())
                _atomic_json(preview_path, preview_job)
            Thread(target=run_preview, daemon=True, name="scenthunter-legacy-preview").start()
            return {"ok": True, "mode": "preview", "status": "running",
                    "message": "Preview accepted. Poll GET /v2/migration/legacy/status?mode=preview. No live database changes are made."}

        previous = None
        with apply_lock:
            if apply_job.get("status") in {"preparing", "running"}:
                return {"ok": True, "mode": "apply", "status": apply_job["status"],
                        "message": "Migration already active; do not submit apply again."}
            if apply_job.get("status") == "completed":
                previous = {"snapshot_sha256": apply_job.get("snapshot_sha256"), "result": apply_job.get("result")}
            apply_job.update(status="preparing", result=None, error=None)
            _atomic_json(apply_path, apply_job)
        try:
            entries, summary = preflight()
            public = {k: v for k, v in summary.items() if not k.startswith("_")}
            if not summary["safe_to_apply"]:
                with apply_lock:
                    apply_job.update(status="failed", result=None,
                                     error="Complete preflight found quarantined or invalid candidates.",
                                     snapshot_sha256=summary["snapshot_sha256"])
                    _atomic_json(apply_path, apply_job)
                return {"ok": False, "mode": "apply",
                        "message": "Preflight found unresolved records. No live database was changed.", **public}
            if previous and previous.get("snapshot_sha256") == summary["snapshot_sha256"]:
                with apply_lock:
                    apply_job.update(status="completed", result=previous.get("result"), error=None,
                                     snapshot_sha256=summary["snapshot_sha256"])
                    _atomic_json(apply_path, apply_job)
                    return {"ok": True, "mode": "apply", **apply_job}
            with apply_lock:
                apply_job.update(status="running", result=None, error=None, snapshot_sha256=summary["snapshot_sha256"])
                _atomic_json(apply_path, apply_job)
            Thread(target=run_migration, args=(entries, summary), daemon=True, name="scenthunter-legacy-migration").start()
            return {"ok": True, "mode": "apply", "status": "running",
                    "snapshot_sha256": summary["snapshot_sha256"],
                    "message": "Migration accepted. Poll GET /v2/migration/legacy/status?mode=apply; do not submit apply again."}
        except Exception as exc:
            with apply_lock:
                apply_job.update(status="failed", result=None, error=f"{type(exc).__name__}: {exc}")
                _atomic_json(apply_path, apply_job)
            if isinstance(exc, HTTPException): raise
            raise HTTPException(status_code=500, detail=f"Migration preflight failed safely: {type(exc).__name__}: {exc}") from exc

    return router
