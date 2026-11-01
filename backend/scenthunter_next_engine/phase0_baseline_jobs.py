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

STORES = (
    "amazon_de", "amazon_fr", "bplatz", "deloox", "easycosmetic", "notino",
    "orioudh", "parfumcity", "parfumzentrum", "perfumemarket", "sabina",
)
COLUMNS = (
    "store", "canonical_product_id", "brand", "fragrance", "concentration",
    "size_ml", "variant_type", "gtin", "external_product_id", "offer_url",
    "price", "currency", "availability", "captured_at", "source",
    "match_confidence", "is_valid_offer",
)
VALID_STOCK = {
    "in_stock", "out_of_stock", "preorder", "backorder",
    "limited_availability",
}
STALE_AFTER_SECONDS = 180


def database_path() -> Path:
    backend = Path(__file__).resolve().parent
    return Path(os.environ.get(
        "SCENTHUNTER_CATALOG_DB", str(backend / "store_catalog.sqlite3")
    )).expanduser().resolve()


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or database_path(), timeout=45)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=45000")
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
            total_stores INTEGER NOT NULL DEFAULT 11,
            processed_stores INTEGER NOT NULL DEFAULT 0,
            output_path TEXT NOT NULL,
            error_message TEXT,
            error_traceback TEXT,
            worker_id TEXT,
            heartbeat_at TEXT,
            duration_seconds REAL
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_phase0_baseline_jobs_queue "
        "ON phase0_baseline_jobs(status, created_at)"
    )
    conn.commit()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_job() -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    output_dir = Path(os.environ.get(
        "PHASE0_BASELINE_DIR", "/data/phase0/baseline"
    )).expanduser()
    output_path = output_dir / f"{job_id}.csv"
    conn = connect()
    try:
        ensure_schema(conn)
        conn.execute(
            """INSERT INTO phase0_baseline_jobs
               (id,status,created_at,total_stores,processed_stores,progress,output_path)
               VALUES(?, 'queued', ?, ?, 0, 0, ?)""",
            (job_id, utc_now(), len(STORES), str(output_path)),
        )
        conn.commit()
    finally:
        conn.close()
    return {"job_id": job_id, "status": "queued"}


def get_job(job_id: str) -> dict[str, Any] | None:
    conn = connect()
    try:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT * FROM phase0_baseline_jobs WHERE id=?", (job_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_job(job_id: str, **values: Any) -> None:
    if not values:
        return
    allowed = {
        "status", "started_at", "finished_at", "progress", "processed_stores",
        "error_message", "error_traceback", "worker_id", "heartbeat_at",
        "duration_seconds",
    }
    if not set(values).issubset(allowed):
        raise ValueError("Unsupported Phase 0 job update field")
    assignments = ", ".join(f"{key}=?" for key in values)
    conn = connect()
    try:
        conn.execute(
            f"UPDATE phase0_baseline_jobs SET {assignments} WHERE id=?"
            (*values.values(), job_id),
        )
        conn.commit()
    finally:
        conn.close()


def recover_stale_jobs() -> int:
    cutoff = datetime.fromtimestamp(
        time.time() - STALE_AFTER_SECONDS, timezone.utc
    ).isoformat(timespec="seconds")
    now = utc_now()
    conn = connect()
    try:
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
    finally:
        conn.close()


def claim_next_job(worker_id: str) -> dict[str, Any] | None:
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT id FROM phase0_baseline_jobs
                WHERE status='queued'
                ORDER BY created_at, id LIMIT 1"""
        ).fetchone()
        if not row:
            conn.commit()
            return None
        job_id = str(row["id"])
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


def _store_cursor(
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
    product = catalog.get(match.canonical_product_id) if (
        match.status is MatchStatus.MATCHED else None
    )
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


def generate_csv(job: dict[str, Any], worker_id: str) -> dict[str, Any]:
    from .catalog_repository import CatalogRepository
    from .canonical_matcher import CanonicalMatcher

    backend = Path(__file__).resolve().parent
    catalog_path = backend / "product_catalog.json"
    db_path = database_path()
    output_path = Path(job["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    started = time.monotonic()

    print(
        f"PHASE0 WORKER JOB START job={job['id']} worker={worker_id} "
        f"stores={len(STORES)} db={db_path} output={output_path}",
        flush=True,
    )
    catalog = CatalogRepository.from_file(catalog_path)
    matcher = CanonicalMatcher(catalog)
    variants_by_id = {
        variant.variant_id: variant
        for product in catalog.all_products()
        for variant in product.variants
    }

    read_conn = sqlite3.connect(
        f"file:{db_path}?mode=ro", uri=True, timeout=45
    )
    read_conn.row_factory = sqlite3.Row
    read_conn.execute("PRAGMA query_only=ON")
    read_conn.execute("PRAGMA busy_timeout=45000")
    table_names = {
        row[0] for row in read_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "store_products" not in table_names:
        raise RuntimeError("SQLite catalog is missing store_products")
    has_variants = "store_product_variants" in table_names
    counts = {
        store: _store_count(read_conn, store, has_variants)
        for store in STORES
    }
    total_offers = sum(counts.values())
    processed_stores = 0
    rows_written = 0

    try:
        with temp_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            for store_index, store in enumerate(STORES):
                store_total = counts[store]
                store_read = 0
                print(
                    f"PHASE0 WORKER STORE START job={job['id']} "
                    f"store={store} offers_expected={store_total}",
                    flush=True,
                )
                for row in _store_cursor(read_conn, store, has_variants):
                    writer.writerow(_offer_row(row, matcher, catalog, variants_by_id))
                    store_read += 1
                    rows_written += 1
                    if store_read % 100 == 0:
                        within_store = (
                            store_read / store_total if store_total else 1.0
                        )
                        progress = min(
                            0.999,
                            (processed_stores + within_store) / len(STORES),
                        )
                        update_job(
                            job["id"], heartbeat_at=utc_now(),
                            progress=progress, processed_stores=processed_stores,
                        )
                processed_stores += 1
                handle.flush()
                update_job(
                    job["id"],
                    heartbeat_at=utc_now(),
                    progress=processed_stores / len(STORES),
                    processed_stores=processed_stores,
                )
                print(
                    f"PHASE0 WORKER STORE DONE job={job['id']} store={store} "
                    f"offers_read={store_read} csv_rows_written={rows_written}",
                    flush=True,
                )
                if store_read != store_total:
                    raise RuntimeError(
                        f"Store row count changed during export for {store}: "
                        f"expected={store_total}, read={store_read}"
                    )
            handle.flush()
            os.fsync(handle.fileno())
        print(
            f"PHASE0 WORKER TEMP FILE CLOSED job={job['id']} "
            f"rows_written={rows_written} bytes={temp_path.stat().st_size}",
            flush=True,
        )
        os.replace(temp_path, output_path)
        print(
            f"PHASE0 WORKER FILE RENAMED job={job['id']} output={output_path}",
            flush=True,
        )
    finally:
        read_conn.close()

    elapsed = round(time.monotonic() - started, 3)
    return {
        "rows_written": rows_written,
        "offers_read": total_offers,
        "stores_processed": processed_stores,
        "duration_seconds": elapsed,
        "output_path": str(output_path),
    }
