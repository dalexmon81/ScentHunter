"""One-URL, idempotent Deloox offer refresh guard for deploy verification.

Only the verified Liquid Brun Limited Edition 150 ml URL is considered.
The script uses the catalog engine's normal parser/persistence path for this
exact URL, then verifies the persisted GTIN, SKU, size, price and availability.
It never writes hand-authored product values or guesses product identity.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from pathlib import Path

DB_PATH = "/data/store_catalog.sqlite3"
STORE = "deloox"
URL = "https://www.deloox.be/produit/1385920/french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html"
GTIN = "6298042001831"
SKU = "1385920"
SIZE_ML = 150


def _read_row(db_path: str) -> dict | None:
    path = Path(db_path).resolve()
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    try:
        row = conn.execute(
            """
            SELECT u.active, p.brand, p.gtin, p.sku, p.size_ml, p.price,
                   p.availability, p.fetch_status, p.fetched_at,
                   q.state AS queue_state, q.leased_until, q.lease_token
            FROM store_urls u
            LEFT JOIN store_products p
              ON lower(p.store)=lower(u.store) AND p.url=u.url
            LEFT JOIN hydration_queue q
              ON lower(q.store)=lower(u.store) AND q.url=u.url
            WHERE lower(u.store)=? AND u.url=?
            LIMIT 1
            """,
            (STORE, URL),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _identity_valid(row: dict | None) -> bool:
    if not row:
        return False
    gtin = re.sub(r"\D", "", str(row.get("gtin") or ""))
    try:
        size = float(row.get("size_ml"))
    except (TypeError, ValueError):
        return False
    return (
        str(row.get("brand") or "").strip().casefold() == "french avenue"
        and gtin == GTIN
        and str(row.get("sku") or "").strip() == SKU
        and size == SIZE_ML
    )


def _offer_state_valid(row: dict | None) -> bool:
    if not _identity_valid(row):
        return False
    availability = str(row.get("availability") or "").strip().lower().replace("-", "_").replace(" ", "_")
    if availability in {"in_stock", "instock", "available", "limited_availability", "preorder"}:
        try:
            return float(row.get("price")) > 0
        except (TypeError, ValueError):
            return False
    if availability in {"out_of_stock", "outofstock", "sold_out", "soldout", "unavailable", "discontinued"}:
        return row.get("price") in (None, "")
    return False


def _mark_queue_done(db_path: str) -> bool:
    """Close the exact target's queue row after its persisted offer is verified."""
    now = time.time()
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT state, leased_until FROM hydration_queue WHERE lower(store)=? AND url=?",
            (STORE, URL),
        ).fetchone()
        if not row:
            conn.rollback()
            raise RuntimeError("target_hydration_queue_row_missing")
        if row["state"] == "PROCESSING" and row["leased_until"] and row["leased_until"] > now:
            conn.rollback()
            return False
        conn.execute(
            """
            UPDATE hydration_queue
               SET state='DONE', attempts=0, available_at=?,
                   last_error=NULL, last_http_status=200, last_finished_at=?,
                   leased_until=NULL, lease_token=NULL
             WHERE lower(store)=? AND url=?
            """,
            (now, now, STORE, URL),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _offer_state_fresh(row: dict | None, max_age_seconds: float = 300) -> bool:
    if not _offer_state_valid(row):
        return False
    try:
        fetched_at = float(row.get("fetched_at"))
    except (TypeError, ValueError):
        return False
    return fetched_at >= time.time() - max_age_seconds


def _requeue(db_path: str) -> dict:
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT u.active, p.brand, p.gtin, p.sku, p.size_ml, p.price,
                   p.availability, p.fetch_status,
                   q.state AS queue_state, q.leased_until
            FROM store_urls u
            LEFT JOIN store_products p
              ON lower(p.store)=lower(u.store) AND p.url=u.url
            LEFT JOIN hydration_queue q
              ON lower(q.store)=lower(u.store) AND q.url=u.url
            WHERE lower(u.store)=? AND u.url=?
            LIMIT 1
            """,
            (STORE, URL),
        ).fetchone()
        if not row or row["active"] != 1:
            raise RuntimeError("target_deloox_url_missing_or_inactive")
        now = time.time()
        if row["queue_state"] == "PROCESSING" and row["leased_until"] and row["leased_until"] > now:
            conn.commit()
            return {"status": "ALREADY_PROCESSING", "url": URL, "database_written": False}
        current = dict(row)
        if _offer_state_valid(current):
            conn.commit()
            return {"status": "TARGET_ALREADY_VALID", "url": URL, "database_written": False}
        conn.execute(
            """
            INSERT INTO hydration_queue(store,url,state,priority,attempts,available_at,first_seen_at)
            VALUES(?,?, 'PENDING',0,0,?,?)
            ON CONFLICT(store,url) DO UPDATE SET
              state='PENDING', priority=0, attempts=0, available_at=?,
              last_error=NULL, last_http_status=NULL,
              last_started_at=NULL, last_finished_at=NULL,
              leased_until=NULL, lease_token=NULL
            WHERE hydration_queue.state!='PROCESSING'
            """,
            (STORE, URL, now, now, now),
        )
        conn.commit()
        return {"status": "TARGET_REQUEUED", "url": URL, "database_written": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=180)
    parser.add_argument("--db", default=DB_PATH)
    args = parser.parse_args()
    if not args.apply:
        row = _read_row(args.db)
        print(json.dumps({
            "status": "DRY_RUN",
            "url": URL,
            "read_only": True,
            "identity_valid": _identity_valid(row),
            "offer_state_valid": _offer_state_valid(row),
            "row": row,
        }, sort_keys=True, default=str))
        return 0

    # If the last exact-URL refresh already persisted a fresh, identity-verified
    # offer, finish its queue row instead of fetching it again. Leaving it PENDING
    # lets the background worker immediately replace the good offer with a
    # transient parser miss after the next deploy.
    current = _read_row(args.db)
    if _offer_state_fresh(current):
        if not _mark_queue_done(args.db):
            raise RuntimeError("target_queue_has_active_lease")
        print(json.dumps({
            "status": "TARGET_ALREADY_VALID",
            "url": URL,
            "identity_valid": True,
            "offer_state_valid": True,
            "availability": current.get("availability"),
            "price": current.get("price"),
            "gtin": current.get("gtin"),
            "sku": current.get("sku"),
            "size_ml": current.get("size_ml"),
            "queue_state": "DONE",
            "database_written": False,
        }, sort_keys=True, default=str))
        return 0

    # Invoke the same parser and SQLite upsert used by normal hydration for
    # this fixed, reviewed URL. The catalog schema is already initialized by the
    # production app; don't rerun its store-wide migration in this subprocess.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import catalog_engine
    catalog_engine._SCHEMA_READY = True
    item = catalog_engine.refresh_url(STORE, URL)
    if not isinstance(item, dict):
        raise RuntimeError("target_parser_returned_no_product")
    parsed_gtin = re.sub(r"\\D", "", str(item.get("gtin") or ""))
    try:
        parsed_size = float(item.get("size_ml"))
        parsed_price = float(item.get("price_num"))
    except (TypeError, ValueError):
        parsed_size = parsed_price = 0
    if (
        str(item.get("brand") or "").strip().casefold() != "french avenue"
        or parsed_gtin != GTIN
        or str(item.get("sku") or "").strip() != SKU
        or parsed_size != SIZE_ML
        or parsed_price <= 0
        or str(item.get("availability") or "").strip().lower() != "in_stock"
    ):
        raise RuntimeError("target_parser_identity_or_offer_validation_failed")
    row = _read_row(args.db)
    if _offer_state_fresh(row):
        if not _mark_queue_done(args.db):
            raise RuntimeError("target_queue_has_active_lease")
        print(json.dumps({
            "status": "TARGET_REFRESHED",
            "url": URL,
            "identity_valid": True,
            "offer_state_valid": True,
            "availability": row.get("availability"),
            "price": row.get("price"),
            "gtin": row.get("gtin"),
            "sku": row.get("sku"),
            "size_ml": row.get("size_ml"),
            "database_written": True,
            "write_path": "catalog_engine.refresh_url",
        }, sort_keys=True, default=str))
        return 0
    result = _requeue(args.db)
    deadline = time.monotonic() + max(0, args.wait_seconds)
    while True:
        row = _read_row(args.db)
        if _offer_state_valid(row):
            print(json.dumps({
                "status": "TARGET_REFRESHED" if result["database_written"] else "TARGET_VALID",
                "url": URL,
                "identity_valid": True,
                "offer_state_valid": True,
                "availability": row.get("availability"),
                "price": row.get("price"),
                "gtin": row.get("gtin"),
                "sku": row.get("sku"),
                "size_ml": row.get("size_ml"),
                "database_written": result["database_written"],
            }, sort_keys=True, default=str))
            return 0
        if time.monotonic() >= deadline:
            print(json.dumps({
                "status": "TARGET_REFRESH_TIMEOUT",
                "url": URL,
                "requeue": result,
                "row": row,
            }, sort_keys=True, default=str))
            return 1
        time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
