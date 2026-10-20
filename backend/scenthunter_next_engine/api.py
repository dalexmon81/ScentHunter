"""Optional FastAPI adapter for the isolated next engine.

Mount this router only behind an explicit feature flag and configure a separate
SCENTHUNTER_NEXT_DB path. Importing this module does not open the database.
"""
from __future__ import annotations

from collections import defaultdict
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
from threading import Lock, Thread
from typing import Any

from .migration import import_legacy_snapshot
from .repository import SQLiteOfferRepository
from .search import SearchRequest, SearchService
from .telemetry import metrics
from .sqlite_export import TABLE_COLUMNS

try:
    from fastapi import APIRouter, Header, HTTPException, Query
except ImportError:  # Core package and tests remain standard-library only.
    APIRouter = None


def _read_legacy_rows(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Read the legacy catalog in SQLite read-only mode; never mutate it."""
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    try:
        existing = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        loaded: dict[str, list[dict[str, Any]]] = {}
        counts: dict[str, int] = {}
        for table in ("store_products", "store_product_variants"):
            if table not in existing:
                loaded[table] = []
                counts[table] = 0
                continue
            actual = {
                str(row["name"])
                for row in conn.execute(f'PRAGMA table_info("{table}")')
            }
            columns = [col for col in TABLE_COLUMNS[table] if col in actual]
            if not columns:
                loaded[table] = []
                counts[table] = 0
                continue
            # Fetch in bounded batches. The returned lists still hold all rows,
            # but this avoids a single unbounded SQLite fetch operation.
            sql = "SELECT " + ",".join(f'"{col}"' for col in columns) + f' FROM "{table}"'
            cursor = conn.execute(sql)
            rows: list[dict[str, Any]] = []
            while True:
                batch = cursor.fetchmany(5_000)
                if not batch:
                    break
                rows.extend(dict(row) for row in batch)
            loaded[table] = rows
            counts[table] = len(rows)
        if "store_products" not in existing:
            raise HTTPException(status_code=409, detail="Legacy table store_products is missing; no import performed.")
        return loaded["store_products"], loaded["store_product_variants"], counts
    finally:
        conn.close()


def _build_entries(
    products: list[dict[str, Any]], variants: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Pair variants only by exact normalized (store, base URL); never fuzzy-match."""
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for variant in variants:
        store = str(variant.get("store") or "").strip().casefold()
        url = str(variant.get("url") or "").strip()
        if store and url:
            by_key[(store, url)].append(variant)

    product_groups: dict[tuple[str, str], int] = defaultdict(int)
    for product in products:
        store = str(product.get("store") or "").strip().casefold()
        url = str(product.get("url") or "").strip()
        if store and url:
            product_groups[(store, url)] += 1

    entries: list[dict[str, Any]] = []
    used_variant_keys: set[tuple[str, str]] = set()
    missing_product_keys = 0
    ambiguous_product_keys = 0
    paired_variants = 0
    for product in products:
        store = str(product.get("store") or "").strip().casefold()
        url = str(product.get("url") or "").strip()
        if not store or not url:
            missing_product_keys += 1
            entries.append({"store": store, "product_row": product, "variant_row": None})
            continue
        key = (store, url)
        matches = by_key.get(key, [])
        if product_groups[key] > 1:
            ambiguous_product_keys += 1
            entries.append({"store": store, "product_row": product, "variant_row": None})
            continue
        if matches:
            used_variant_keys.add(key)
            paired_variants += len(matches)
            for variant in matches:
                entries.append({"store": store, "product_row": product, "variant_row": variant})
        else:
            entries.append({"store": store, "product_row": product, "variant_row": None})

    orphan_variants = sum(
        len(rows) for key, rows in by_key.items()
        if key not in used_variant_keys and product_groups.get(key, 0) == 0
    )
    ambiguous_variant_rows = sum(
        len(rows) for key, rows in by_key.items()
        if product_groups.get(key, 0) > 1
    )
    return entries, {
        "products_without_store_or_url": missing_product_keys,
        "duplicate_product_keys": ambiguous_product_keys,
        "orphan_variant_rows": orphan_variants,
        "variants_under_ambiguous_product_keys": ambiguous_variant_rows,
        "paired_variant_rows": paired_variants,
        "candidate_observations": len(entries),
    }


def create_router(db_path: str | Path | None = None):
    if APIRouter is None:
        raise RuntimeError("FastAPI is required to create the next-engine API router")
    if db_path is None:
        from .runtime import validated_database_path
        path = validated_database_path()
    else:
        path = Path(db_path).expanduser().resolve()
        legacy_path = (
            os.environ.get("SCENTHUNTER_LEGACY_DB")
            or os.environ.get("SCENTHUNTER_CATALOG_DB", "")
        ).strip()
        if legacy_path and path == Path(legacy_path).expanduser().resolve():
            raise RuntimeError("next-engine database must not be the legacy catalog database")

    repository = SQLiteOfferRepository(path)
    search_service = SearchService(repository)
    router = APIRouter(prefix="/v2", tags=["next-engine"])
    migration_lock = Lock()
    migration_job: dict[str, Any] = {"status": "idle", "result": None, "error": None}

    def authorize(token: str | None) -> None:
        configured = os.environ.get("SCENTHUNTER_MIGRATION_TOKEN", "").strip()
        if not configured:
            raise HTTPException(
                status_code=503,
                detail="Legacy migration is disabled: SCENTHUNTER_MIGRATION_TOKEN is not configured.",
            )
        if not token or not secrets.compare_digest(token, configured):
            raise HTTPException(status_code=401, detail="Invalid migration token.")

    def preflight() -> tuple[list[dict[str, Any]], dict[str, Any]]:
        legacy_setting = (
            os.environ.get("SCENTHUNTER_LEGACY_DB")
            or os.environ.get("SCENTHUNTER_CATALOG_DB", "")
        ).strip()
        if not legacy_setting:
            raise HTTPException(
                status_code=503,
                detail="Legacy migration is disabled: SCENTHUNTER_CATALOG_DB is not configured.",
            )
        legacy_path = Path(legacy_setting).expanduser().resolve()
        if legacy_path == path.expanduser().resolve():
            raise HTTPException(status_code=500, detail="Legacy and next-engine database paths must differ.")
        if not legacy_path.is_file():
            raise HTTPException(status_code=503, detail="Configured legacy database file is unavailable.")

        products, variants, table_counts = _read_legacy_rows(legacy_path)
        entries, pairing = _build_entries(products, variants)
        if not entries:
            raise HTTPException(status_code=409, detail="No legacy product rows found; no import performed.")

        # Keep preview lightweight. Full row validation is performed in the
        # isolated staging database during mode=apply. If any row is rejected,
        # the staged import is discarded before the live V2 DB is touched.
        safe = (
            pairing["products_without_store_or_url"] == 0
            and pairing["duplicate_product_keys"] == 0
            and pairing["orphan_variant_rows"] == 0
            and pairing["variants_under_ambiguous_product_keys"] == 0
            and len(entries) > 0
        )
        summary = {
            "safe_to_apply": safe,
            "legacy_tables": table_counts,
            "pairing": pairing,
            "preflight": {
                "processed": len(entries),
                "valid": None,
                "rejected_count": None,
                "validation": "deferred_to_staging_apply",
                "rejections": [],
            },
            "target_counts_before": repository.counts(),
        }
        return entries, summary

    @router.get("/health")
    def health() -> dict[str, Any]:
        counts = repository.counts()
        return {"ok": True, "engine": "next", "database": "separate", "counts": counts}

    @router.get("/metrics")
    def engine_metrics() -> dict[str, Any]:
        # No URL, query, or user-level labels are exposed in this endpoint.
        return {"engine": "next", **metrics.snapshot()}

    @router.get("/search")
    def search(q: str = Query(default="", max_length=200),
               store: str | None = Query(default=None, max_length=64),
               currency: str | None = Query(default=None, min_length=3, max_length=3),
               limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
        try:
            request = SearchRequest(query=q, store=store, currency=currency, limit=limit)
            return search_service.search(request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def run_migration(entries: list[dict[str, Any]], summary: dict[str, Any]) -> None:
        stage_path: Path | None = None
        try:
            if any(repository.counts().values()):
                raise RuntimeError("The V2 database is not empty. No import performed.")
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{path.name}.migration-", suffix=".sqlite3", dir=str(path.parent)
            )
            os.close(fd)
            stage_path = Path(temp_name)
            stage = SQLiteOfferRepository(stage_path)
            staged_result = import_legacy_snapshot(entries, stage)
            if staged_result["rejected_count"] != 0:
                raise RuntimeError("Staging import rejected rows. Live V2 database was not changed.")
            staged_counts = stage.counts()
            if staged_counts["observations"] == 0:
                raise RuntimeError("Staging import produced no observations. Live V2 database was not changed.")
            if any(repository.counts().values()):
                raise RuntimeError("The V2 database changed during migration. Staged data was discarded.")
            with sqlite3.connect(str(stage_path), timeout=30) as source_conn:
                with sqlite3.connect(str(path), timeout=30) as destination_conn:
                    source_conn.backup(destination_conn)
            result = {
                "legacy_tables": summary["legacy_tables"],
                "pairing": summary["pairing"],
                "processed": staged_result["processed"],
                "imported": staged_result["imported"],
                "replayed": staged_result["replayed"],
                "rejected_count": staged_result["rejected_count"],
                "counts": repository.counts(),
            }
            with migration_lock:
                migration_job.update({"status": "completed", "result": result, "error": None})
        except Exception as exc:
            with migration_lock:
                migration_job.update({"status": "failed", "result": None, "error": f"{type(exc).__name__}: {exc}"})
        finally:
            if stage_path is not None:
                for candidate in (stage_path, Path(str(stage_path) + "-wal"), Path(str(stage_path) + "-shm")):
                    try:
                        candidate.unlink(missing_ok=True)
                    except OSError:
                        pass

    @router.get("/migration/legacy/status")
    def migration_status(
        migration_token: str | None = Header(default=None, alias="X-ScentHunter-Migration-Token"),
    ) -> dict[str, Any]:
        authorize(migration_token)
        with migration_lock:
            snapshot = dict(migration_job)
        return {"ok": snapshot["status"] != "failed", "mode": "apply", **snapshot}

    @router.post("/migration/legacy")
    def migrate_legacy(
        mode: str = Query(default="preview", pattern="^(preview|apply)$"),
        migration_token: str | None = Header(default=None, alias="X-ScentHunter-Migration-Token"),
    ) -> dict[str, Any]:
        authorize(migration_token)
        if mode == "apply":
            with migration_lock:
                if migration_job["status"] in ("preparing", "running"):
                    return {"ok": True, "mode": "apply", "status": migration_job["status"], "message": "Migration already active; do not submit apply again."}
                if migration_job["status"] == "completed":
                    return {"ok": True, "mode": "apply", **migration_job}
                migration_job.update({"status": "preparing", "result": None, "error": None})
        try:
            entries, summary = preflight()
            if not summary["safe_to_apply"]:
                if mode == "apply":
                    with migration_lock:
                        migration_job.update({"status": "failed", "result": None, "error": "Preflight found unsafe pairing structure."})
                return {"ok": False, "mode": mode, "message": "Preflight found unsafe pairing structure. Nothing was written to the live V2 database.", **summary}
            if mode == "preview":
                return {"ok": True, "mode": "preview", "message": "Structural preflight passed. Full row validation is deferred to the isolated staging import during mode=apply. No live database was changed.", **summary}
            if any(repository.counts().values()):
                with migration_lock:
                    migration_job.update({"status": "failed", "result": None, "error": "V2 database is not empty; no import performed."})
                raise HTTPException(status_code=409, detail="The V2 database is not empty. No import performed.")
            with migration_lock:
                migration_job["status"] = "running"
            Thread(target=run_migration, args=(entries, summary), daemon=True, name="scenthunter-legacy-migration").start()
            return {"ok": True, "mode": "apply", "status": "running", "message": "Migration accepted in background. Poll GET /v2/migration/legacy/status; do not submit apply again."}
        except Exception as exc:
            if mode == "apply":
                with migration_lock:
                    if migration_job["status"] == "preparing":
                        migration_job.update({"status": "failed", "result": None, "error": f"{type(exc).__name__}: {exc}"})
            raise

    return router
