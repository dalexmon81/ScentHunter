"""Persistent asynchronous Phase 0 baseline jobs and streaming CSV generation."""
from __future__ import annotations

import csv
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

# Phase 0 is scoped to the nine agreed active retailers. Excluded retailers
# are not scheduled, exported, counted, or validated by this worker.
STORES = (
    "bplatz", "deloox", "easycosmetic", "notino", "orioudh",
    "parfumcity", "parfumzentrum", "perfumemarket", "sabina",
)
COLUMNS = (
    "store", "canonical_product_id", "brand", "fragrance", "concentration",
    "size_ml", "variant_type", "gtin", "external_product_id", "offer_url",
    "price", "currency", "availability", "captured_at", "source",
    "match_confidence", "is_valid_offer", "store_status",
)
HEARTBEAT_INTERVAL_SECONDS = 20
STORE_TIMEOUT_SECONDS = 300
VALID_STOCK = {
    "in_stock", "out_of_stock", "preorder", "backorder",
    "limited_availability",
}
STALE_AFTER_SECONDS = 600


def jobs_database_path() -> Path:
    # The queue shares the persistent Fly volume, not the catalog database.
    # The catalog has long-running writers; keeping queue writes in a dedicated
    # SQLite file guarantees that those writers cannot delay POST /start.
    return Path(os.environ.get(
        "PHASE0_JOBS_DB", "/data/phase0/phase0_jobs.sqlite3"
    )).expanduser().resolve()


def catalog_database_path() -> Path:
    backend = Path(__file__).resolve().parent.parent
    return Path(os.environ.get(
        "SCENTHUNTER_CATALOG_DB", str(backend / "store_catalog.sqlite3")
    )).expanduser().resolve()


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or jobs_database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=2)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=2000")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS phase0_baseline_jobs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed')),
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            progress REAL NOT NULL DEFAULT 0,
            total_stores INTEGER NOT NULL DEFAULT 9,
            processed_stores INTEGER NOT NULL DEFAULT 0,
            output_path TEXT NOT NULL,
            error_message TEXT,
            error_traceback TEXT,
            worker_id TEXT,
            current_store TEXT,
            heartbeat_at TEXT,
            duration_seconds REAL
        )"""
    )
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(phase0_baseline_jobs)")}
    if "current_store" not in columns:
        conn.execute("ALTER TABLE phase0_baseline_jobs ADD COLUMN current_store TEXT")
    # Upgrade legacy queued jobs and retire legacy in-flight jobs that were
    # created with the old 11-retailer contract. They must not resume against
    # a nine-retailer worker or be mistaken for a current-scope CSV.
    now = utc_now()
    conn.execute(
        """UPDATE phase0_baseline_jobs
              SET status='failed', finished_at=?,
                  error_message='Phase 0 store scope changed from 11 to 9; restart the baseline',
                  error_traceback=COALESCE(error_traceback, '')
            WHERE status='running' AND total_stores<>?""",
        (now, len(STORES)),
    )
    conn.execute(
        "UPDATE phase0_baseline_jobs SET total_stores=? WHERE status='queued'",
        (len(STORES),),
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_phase0_baseline_jobs_queue "
        "ON phase0_baseline_jobs(status, created_at)"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS phase0_baseline_job_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            at TEXT NOT NULL,
            event TEXT NOT NULL,
            store TEXT,
            message TEXT,
            details TEXT
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_phase0_baseline_job_events_job "
        "ON phase0_baseline_job_events(job_id, id)"
    )
    conn.commit()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_job_event(
    job_id: str, event: str, *, store: str | None = None,
    message: str | None = None, details: dict[str, Any] | None = None,
) -> None:
    import json
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO phase0_baseline_job_events
               (job_id, at, event, store, message, details)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (job_id, utc_now(), event, store, message,
             json.dumps(details, ensure_ascii=False, default=str) if details else None),
        )
        conn.commit()
    finally:
        conn.close()


def get_job_events(job_id: str) -> list[dict[str, Any]]:
    import json
    conn = connect()
    try:
        rows = conn.execute(
            """SELECT id, job_id, at, event, store, message, details
                 FROM phase0_baseline_job_events
                WHERE job_id=? ORDER BY id""",
            (job_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            if item.get("details"):
                try:
                    item["details"] = json.loads(item["details"])
                except (TypeError, ValueError):
                    pass
            result.append(item)
        return result
    finally:
        conn.close()


def create_job() -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    output_dir = Path(os.environ.get(
        "PHASE0_BASELINE_DIR", "/data/phase0/baseline"
    )).expanduser()
    output_path = output_dir / f"{job_id}.csv"
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO phase0_baseline_jobs
               (id,status,created_at,total_stores,processed_stores,progress,output_path)
               VALUES(?, 'queued', ?, ?, 0, 0, ?)""",
            (job_id, utc_now(), len(STORES), str(output_path)),
        )
        conn.commit()
    finally:
        conn.close()
    record_job_event(job_id, "job_created", message="Baseline job queued")
    return {"job_id": job_id, "status": "queued"}


def get_job(job_id: str) -> dict[str, Any] | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM phase0_baseline_jobs WHERE id=?", (job_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_latest_job() -> dict[str, Any] | None:
    """Read the newest durable job without acquiring a write lock."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM phase0_baseline_jobs ORDER BY created_at DESC, id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_job(job_id: str, **values: Any) -> None:
    if not values:
        return
    allowed = {
        "status", "started_at", "finished_at", "progress", "processed_stores",
        "error_message", "error_traceback", "worker_id", "current_store", "heartbeat_at",
        "duration_seconds",
    }
    if not set(values).issubset(allowed):
        raise ValueError("Unsupported Phase 0 job update field")
    assignments = ", ".join(f"{key}=?" for key in values)
    conn = connect()
    try:
        conn.execute(
            f"UPDATE phase0_baseline_jobs SET {assignments} WHERE id=?",
            (*values.values(), job_id),
        )
        conn.commit()
    finally:
        conn.close()
    if "heartbeat_at" in values:
        record_job_event(job_id, "heartbeat", message="Worker heartbeat")
    if values.get("status") == "completed":
        record_job_event(job_id, "job_completed", message="Baseline job completed")
    elif values.get("status") == "failed":
        record_job_event(
            job_id, "job_failed",
            message=str(values.get("error_message") or "Baseline job failed"),
        )


def recover_stale_jobs() -> int:
    cutoff = datetime.fromtimestamp(
        time.time() - STALE_AFTER_SECONDS, timezone.utc
    ).isoformat(timespec="seconds")
    now = utc_now()
    conn = connect()
    try:
        # Avoid acquiring a write lock when there is no stale job to recover.
        stale = conn.execute(
            """SELECT id FROM phase0_baseline_jobs
                WHERE status='running'
                  AND (heartbeat_at IS NULL OR heartbeat_at < ?)
                LIMIT 1""",
            (cutoff,),
        ).fetchone()
        if not stale:
            return 0
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            """UPDATE phase0_baseline_jobs
                  SET status='failed', finished_at=?,
                      error_message='Worker heartbeat expired; job was not resumed',
                      error_traceback=COALESCE(error_traceback, ''),
                      duration_seconds=CASE
                        WHEN started_at IS NOT NULL
                        THEN MAX(0, strftime('%s', ?) - strftime('%s', started_at))
                        ELSE NULL END
                WHERE status='running'
                  AND (heartbeat_at IS NULL OR heartbeat_at < ?)""",
            (now, now, cutoff),
        )
        conn.commit()
        return cur.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def claim_next_job(worker_id: str) -> dict[str, Any] | None:
    conn = connect()
    try:
        # A read-only peek avoids taking SQLite's single-writer lock every
        # five seconds while the durable queue is empty.
        row = conn.execute(
            """SELECT id FROM phase0_baseline_jobs
                WHERE status='queued'
                ORDER BY created_at, id LIMIT 1"""
        ).fetchone()
        if not row:
            return None
        job_id = str(row["id"])
        conn.execute("BEGIN IMMEDIATE")
        now = utc_now()
        cur = conn.execute(
            """UPDATE phase0_baseline_jobs
                  SET status='running', worker_id=?, started_at=?,
                      heartbeat_at=?, progress=0, processed_stores=0,
                      error_message=NULL, error_traceback=NULL
                WHERE id=? AND status='queued'""",
            (worker_id, now, now, job_id),
        )
        conn.commit()
        if cur.rowcount != 1:
            return None
        record_job_event(job_id, "worker_claimed", message=f"Worker {worker_id} claimed job")
        record_job_event(job_id, "job_started", message="Baseline processing started")
        return get_job(job_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _store_count(conn: sqlite3.Connection, store: str, has_variants: bool) -> int:
    if has_variants:
        row = conn.execute(
            """SELECT
                 (SELECT COUNT(*) FROM store_product_variants WHERE store=?)
                 +
                 (SELECT COUNT(*) FROM store_products p
                    WHERE p.store=?
                      AND NOT EXISTS (
                        SELECT 1 FROM store_product_variants v
                         WHERE v.store=p.store AND v.url=p.url
                      )) AS n""",
            (store, store),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM store_products WHERE store=?", (store,)
        ).fetchone()
    return int(row["n"] or 0)


def iter_store_rows(
    conn: sqlite3.Connection, store: str, has_variants: bool
) -> Iterator[sqlite3.Row]:
    if has_variants:
        sql = """SELECT * FROM (
            SELECT store, COALESCE(NULLIF(variant_url,''),url) AS offer_url,
                   url AS product_url, name, brand, sku, gtin, mpn, size_ml,
                   concentration, price, currency, availability, fetched_at,
                   'store_product_variants' AS source, variant_key
              FROM store_product_variants WHERE store=?
            UNION ALL
            SELECT p.store, p.url AS offer_url, p.url AS product_url,
                   p.name, p.brand, p.sku, p.gtin, p.mpn, p.size_ml,
                   p.concentration, p.price, p.currency, p.availability,
                   p.fetched_at, 'store_products' AS source, '' AS variant_key
              FROM store_products p
             WHERE p.store=?
               AND NOT EXISTS (
                   SELECT 1 FROM store_product_variants v
                    WHERE v.store=p.store AND v.url=p.url
               )
        ) ORDER BY product_url, offer_url, variant_key"""
        return iter(conn.execute(sql, (store, store)))
    return iter(conn.execute(
        """SELECT store, url AS offer_url, url AS product_url, name, brand,
                  sku, gtin, mpn, size_ml, concentration, price, currency,
                  availability, fetched_at, 'store_products' AS source,
                  '' AS variant_key
             FROM store_products WHERE store=? ORDER BY url""",
        (store,),
    ))


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if result > 0 else None
    except (TypeError, ValueError):
        return None


def _captured_at(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _valid_url(value: Any) -> bool:
    from urllib.parse import urlparse
    try:
        parsed = urlparse(str(value or "").strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


def _offer_row(row: sqlite3.Row, matcher: Any, catalog: Any,
               variants_by_id: dict[str, Any]) -> dict[str, Any]:
    from decimal import Decimal
    from .models import RetailerOffer, MatchStatus

    raw_name = str(row["name"] or "unknown product")
    brand_raw = str(row["brand"]) if row["brand"] else None
    size = _number(row["size_ml"])
    size_int = int(size) if size is not None and size.is_integer() else None
    gtin = str(row["gtin"]) if row["gtin"] else ""
    sku = str(row["sku"]) if row["sku"] else ""
    mpn = str(row["mpn"]) if row["mpn"] else ""
    currency = str(row["currency"] or "").upper()
    price = _number(row["price"])
    availability = str(row["availability"] or "")
    offer = RetailerOffer(
        retailer=str(row["store"]),
        raw_name=raw_name,
        product_url=str(row["offer_url"]) if row["offer_url"] else None,
        retailer_product_id=gtin or sku or mpn or None,
        brand_raw=brand_raw,
        size_ml=size_int,
        price=Decimal(str(price)) if price is not None else None,
        currency=currency or "EUR",
        availability=availability or None,
        raw_payload={"gtin": gtin, "sku": sku, "mpn": mpn,
                     "concentration": row["concentration"]},
    )
    match = matcher.match(offer)
    product = catalog.get(match.canonical_product_id) if match.status is MatchStatus.MATCHED else None
    variant = variants_by_id.get(match.canonical_variant_id) if product else None
    valid_price = price is not None and len(currency) == 3 and currency.isalpha()
    valid_stock = availability.strip().lower() in VALID_STOCK
    valid_url = _valid_url(row["offer_url"])
    return {
        "store": str(row["store"]),
        "canonical_product_id": match.canonical_product_id or "",
        "brand": product.brand if product else (brand_raw or ""),
        "fragrance": product.name if product else raw_name,
        "concentration": str(row["concentration"] or (
            product.concentration if product else ""
        ) or ""),
        "size_ml": size if size is not None else (
            variant.size_ml if variant else ""
        ),
        "variant_type": (
            variant.label or (variant.aliases[0] if variant.aliases else "")
            if variant else ("variant" if row["source"] == "store_product_variants" else "base")
        ),
        "gtin": gtin,
        "external_product_id": sku or mpn,
        "offer_url": str(row["offer_url"] or ""),
        "price": price if price is not None else "",
        "currency": currency,
        "availability": availability,
        "captured_at": _captured_at(row["fetched_at"]),
        "source": str(row["source"]),
        "match_confidence": str(match.confidence) if match.confidence is not None else "",
        "is_valid_offer": "true" if valid_price and valid_url and valid_stock else "false",
    }


def _export_store_chunk(store: str, db_path: str, catalog_path: str,
                        chunk_path: str, result_queue: Any) -> None:
    """Export one retailer in an isolated child process so it can be terminated."""
    try:
        from .catalog_repository import CatalogRepository
        from .canonical_matcher import CanonicalMatcher

        catalog = CatalogRepository.from_file(Path(catalog_path))
        matcher = CanonicalMatcher(catalog)
        variants_by_id = {
            variant.variant_id: variant
            for product in catalog.all_products()
            for variant in product.variants
        }
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=45)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=45000")
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if "store_products" not in tables:
            raise RuntimeError("SQLite catalog is missing store_products")
        has_variants = "store_product_variants" in tables
        expected = _store_count(conn, store, has_variants)
        written = 0
        with Path(chunk_path).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            for row in iter_store_rows(conn, store, has_variants):
                data = _offer_row(row, matcher, catalog, variants_by_id)
                data["store_status"] = "completed"
                writer.writerow(data)
                written += 1
            if written == 0:
                writer.writerow({"store": store, "store_status": "completed",
                                 "is_valid_offer": "false"})
        conn.close()
        if written != expected:
            raise RuntimeError(
                f"Store row count mismatch for {store}: expected={expected}, read={written}"
            )
        result_queue.put({"ok": True, "offers_read": written})
    except BaseException as exc:
        result_queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        raise


def generate_csv(job: dict[str, Any], worker_id: str) -> dict[str, Any]:
    import multiprocessing
    import threading
    backend = Path(__file__).resolve().parent.parent
    catalog_path = backend / "product_catalog.json"
    db_path = catalog_database_path()
    output_path = Path(job["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    started = time.monotonic()
    heartbeat_stop = threading.Event()
    heartbeat_errors: list[str] = []
    progress_lock = threading.Lock()
    progress_state = {"processed": 0, "store": None}

    print(
        f"PHASE0 WORKER JOB START job={job['id']} worker={worker_id} "
        f"stores={len(STORES)} db={db_path} output={output_path}",
        flush=True,
    )
    print(
        f"PHASE0 WORKER CATALOG PATH job={job['id']} path={catalog_path} "
        f"exists={catalog_path.is_file()}",
        flush=True,
    )
    if not catalog_path.is_file():
        raise FileNotFoundError(f"Phase 0 catalog file not found: {catalog_path}")
    if not db_path.is_file():
        raise FileNotFoundError(f"Phase 0 catalog database not found: {db_path}")

    def heartbeat_loop() -> None:
        while not heartbeat_stop.wait(HEARTBEAT_INTERVAL_SECONDS):
            try:
                with progress_lock:
                    processed = progress_state["processed"]
                    current = progress_state["store"]
                update_job(
                    job["id"], heartbeat_at=utc_now(),
                    progress=min(0.999, processed / len(STORES)),
                    processed_stores=processed, current_store=current,
                )
                record_job_event(
                    job["id"], "heartbeat", store=current,
                    message="Independent timed worker heartbeat",
                )
                print(
                    f"PHASE0 WORKER HEARTBEAT job={job['id']} "
                    f"processed_stores={processed} current_store={current}",
                    flush=True,
                )
            except Exception as exc:
                heartbeat_errors.append(f"{type(exc).__name__}: {exc}")
                print(f"PHASE0 WORKER HEARTBEAT ERROR job={job['id']} error={exc}", flush=True)

    heartbeat_thread = threading.Thread(
        target=heartbeat_loop, name=f"phase0-heartbeat-{job['id']}", daemon=True
    )
    heartbeat_thread.start()
    ctx = multiprocessing.get_context("fork")
    rows_written = 0
    offers_read = 0
    processed_stores = 0
    store_statuses: dict[str, str] = {}
    try:
        with temp_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            for store in STORES:
                with progress_lock:
                    progress_state["store"] = store
                record_job_event(job["id"], "store_started", store=store,
                                 message=f"Store export started; timeout={STORE_TIMEOUT_SECONDS}s")
                chunk_path = output_path.parent / f".{job['id']}.{store}.csv.tmp"
                result_queue = ctx.Queue()
                process = ctx.Process(
                    target=_export_store_chunk,
                    args=(store, str(db_path), str(catalog_path), str(chunk_path), result_queue),
                    name=f"phase0-{store}",
                )
                print(f"PHASE0 WORKER STORE START job={job['id']} store={store}", flush=True)
                process.start()
                process.join(STORE_TIMEOUT_SECONDS)
                if process.is_alive():
                    process.terminate()
                    process.join(10)
                    if process.is_alive() and hasattr(process, "kill"):
                        process.kill()
                        process.join(5)
                    store_status = "timeout"
                    error = f"Store exceeded {STORE_TIMEOUT_SECONDS}s timeout"
                else:
                    try:
                        result = result_queue.get(timeout=2)
                    except Exception:
                        result = {"ok": False, "error": f"Store process exited {process.exitcode} without result"}
                    store_status = "completed" if result.get("ok") and process.exitcode == 0 else "failed"
                    error = result.get("error")
                result_queue.close()
                if chunk_path.is_file():
                    if store_status == "completed":
                        with chunk_path.open("r", newline="", encoding="utf-8") as chunk:
                            reader = csv.DictReader(chunk)
                            for row in reader:
                                writer.writerow(row)
                                if row.get("source"):
                                    rows_written += 1
                        offers_read += int(result.get("offers_read", 0))
                    else:
                        chunk_path.unlink(missing_ok=True)
                if store_status != "completed":
                    writer.writerow({"store": store, "store_status": store_status,
                                     "is_valid_offer": "false"})
                else:
                    chunk_path.unlink(missing_ok=True)
                processed_stores += 1
                store_statuses[store] = store_status
                handle.flush()
                with progress_lock:
                    progress_state["processed"] = processed_stores
                update_job(
                    job["id"], heartbeat_at=utc_now(),
                    progress=processed_stores / len(STORES),
                    processed_stores=processed_stores, current_store=store,
                )
                record_job_event(
                    job["id"], f"store_{store_status}", store=store,
                    message=error or f"Store finished with status={store_status}",
                    details={"status": store_status},
                )
                print(
                    f"PHASE0 WORKER STORE DONE job={job['id']} store={store} "
                    f"status={store_status} error={error or ''}",
                    flush=True,
                )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, output_path)
        record_job_event(
            job["id"], "csv_written", message="Baseline CSV atomically published",
            details={"output_path": str(output_path), "size_bytes": output_path.stat().st_size,
                     "store_statuses": store_statuses},
        )
        directory_fd = os.open(output_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=HEARTBEAT_INTERVAL_SECONDS + 2)
        for leftover in output_path.parent.glob(f".{job['id']}.*.csv.tmp"):
            leftover.unlink(missing_ok=True)

    elapsed = round(time.monotonic() - started, 3)
    return {
        "rows_written": rows_written,
        "offers_read": offers_read,
        "stores_processed": processed_stores,
        "store_statuses": store_statuses,
        "duration_seconds": elapsed,
        "output_path": str(output_path),
    }


# Lightweight worker smoke jobs share the existing durable Phase 0 queue database.
SMOKE_STORES = STORES


def ensure_smoke_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS phase0_smoke_jobs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed')),
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            heartbeat_at TEXT,
            worker_id TEXT,
            output_path TEXT NOT NULL,
            error_message TEXT
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_phase0_smoke_queue "
        "ON phase0_smoke_jobs(status, created_at)"
    )
    conn.commit()


def create_smoke_job() -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    output_dir = Path("/data/phase0/smoke")
    output_path = output_dir / f"{job_id}.csv"
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO phase0_smoke_jobs
               (id,status,created_at,output_path) VALUES(?, 'queued', ?, ?)""",
            (job_id, utc_now(), str(output_path)),
        )
        conn.commit()
    finally:
        conn.close()
    return {"job_id": job_id, "status": "queued"}


def get_smoke_job(job_id: str) -> dict[str, Any] | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM phase0_smoke_jobs WHERE id=?", (job_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def claim_next_smoke_job(worker_id: str) -> dict[str, Any] | None:
    conn = connect()
    try:
        row = conn.execute(
            """SELECT id FROM phase0_smoke_jobs WHERE status='queued'
               ORDER BY created_at, id LIMIT 1"""
        ).fetchone()
        if not row:
            return None
        job_id = str(row["id"])
        conn.execute("BEGIN IMMEDIATE")
        now = utc_now()
        cur = conn.execute(
            """UPDATE phase0_smoke_jobs SET status='running', worker_id=?,
               started_at=?, heartbeat_at=? WHERE id=? AND status='queued'""",
            (worker_id, now, now, job_id),
        )
        conn.commit()
        if cur.rowcount != 1:
            return None
        return get_smoke_job(job_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def finish_smoke_job(job_id: str, **values: Any) -> None:
    allowed = {"status", "finished_at", "heartbeat_at", "error_message"}
    if not set(values).issubset(allowed):
        raise ValueError("Unsupported smoke job update field")
    assignments = ", ".join(f"{key}=?" for key in values)
    conn = connect()
    try:
        conn.execute(
            f"UPDATE phase0_smoke_jobs SET {assignments} WHERE id=?",
            (*values.values(), job_id),
        )
        conn.commit()
    finally:
        conn.close()


def generate_smoke_csv(job: dict[str, Any]) -> dict[str, Any]:
    output_path = Path(job["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(".csv.tmp")
    with temp_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("store", "status"))
        writer.writerows((store, "ok") for store in SMOKE_STORES)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, output_path)
    directory_fd = os.open(output_path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return {"output_path": str(output_path), "rows_written": len(SMOKE_STORES)}


def get_latest_smoke_job() -> dict[str, Any] | None:
    conn = connect()
    try:
        try:
            row = conn.execute(
                "SELECT * FROM phase0_smoke_jobs ORDER BY created_at DESC, id DESC LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise
        return dict(row) if row else None
    finally:
        conn.close()
