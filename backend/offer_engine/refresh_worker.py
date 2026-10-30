"""Independent, rate-limited Offer Engine catalog refresh worker.

The worker is opt-in and never runs in the HTTP request path. It rotates through
canonical products, asks configured retailer connectors to discover them, and
persists observations through the existing verification policy. It deliberately
does not infer variants or publish unverified observations.
"""
from __future__ import annotations

import os
import signal
import sqlite3
import time
from typing import Any

from .runtime import CATALOG_PATH, connect_offer_engine_db, run_offer_engine, seed_canonical_catalog
try:
    from scenthunter_next_engine.catalog_repository import CatalogRepository
except ModuleNotFoundError:
    from backend.scenthunter_next_engine.catalog_repository import CatalogRepository


def build_product_queries(catalog: Any) -> list[str]:
    """Return one deterministic brand/name/size query for each explicit variant."""
    queries: list[str] = []
    seen: set[str] = set()
    for product in catalog.all_products():
        for variant in product.variants:
            if variant.size_ml is None:
                continue
            parts = [product.brand, product.name]
            if variant.label:
                label = variant.label.strip()
                folded_label = label.casefold()
                if "limited edition" in folded_label:
                    parts.append("Limited Edition")
                elif folded_label not in {product.name.casefold(), product.brand.casefold()}:
                    parts.append(label)
            parts.append(f"{int(variant.size_ml)} ml")
            query = " ".join(part.strip() for part in parts if part and part.strip())
            key = query.casefold()
            if query and key not in seen:
                seen.add(key)
                queries.append(query)
    return queries

def _execute(connection: Any, sql: str, params: tuple = ()) -> Any:
    sqlite_backend = isinstance(connection, sqlite3.Connection)
    if sqlite_backend:
        sql = sql.replace("%s", "?")
    cursor = connection.cursor()
    cursor.execute(sql, params)
    return cursor


def _ensure_scheduler_row(connection: Any) -> None:
    cursor = _execute(
        connection,
        "INSERT INTO sh_refresh_scheduler(id, product_cursor) VALUES (1, 0) ON CONFLICT(id) DO NOTHING",
    )
    cursor.close()
    connection.commit()


def _next_query(connection: Any, queries: list[str]) -> str:
    if not queries:
        raise RuntimeError("offer_engine_catalog_has_no_refreshable_products")
    _ensure_scheduler_row(connection)
    sqlite_backend = isinstance(connection, sqlite3.Connection)
    cursor = connection.cursor()
    try:
        cursor.execute("BEGIN IMMEDIATE" if sqlite_backend else "BEGIN")
        lock_clause = "" if sqlite_backend else " FOR UPDATE"
        select = _execute(
            connection,
            "SELECT product_cursor FROM sh_refresh_scheduler WHERE id=1" + lock_clause,
        )
        row = select.fetchone()
        select.close()
        position = int(row[0] or 0) % len(queries)
        update = _execute(
            connection,
            """UPDATE sh_refresh_scheduler
                  SET product_cursor=%s, last_started_at=CURRENT_TIMESTAMP,
                      last_error=NULL
                WHERE id=1""",
            ((position + 1) % len(queries),),
        )
        update.close()
        connection.commit()
        return queries[position]
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def _record_result(connection: Any, error: str | None = None) -> None:
    cursor = _execute(
        connection,
        """UPDATE sh_refresh_scheduler
              SET last_finished_at=CURRENT_TIMESTAMP, last_error=%s
            WHERE id=1""",
        (error[:1000] if error else None,),
    )
    cursor.close()
    connection.commit()


def refresh_once() -> dict[str, Any]:
    """Refresh one canonical product across configured independent connectors."""
    catalog = CatalogRepository.from_file(CATALOG_PATH)
    queries = build_product_queries(catalog)
    connection = connect_offer_engine_db()
    try:
        # A missing migration is a hard failure; the worker must never silently
        # create production schema or alter the migration safety switches.
        cursor = _execute(connection, "SELECT product_cursor FROM sh_refresh_scheduler LIMIT 1")
        cursor.close()
        query = _next_query(connection, queries)
    finally:
        connection.close()

    try:
        result = run_offer_engine(query)
        summary = {
            "query": query,
            "connectors": len(result.connectors),
            "listings_seen": result.listings_seen,
            "observations_written": result.observations_written,
            "offers_published": result.offers_published,
            "failed_connectors": [item.retailer for item in result.connectors if item.status == "failed"],
        }
        connection = connect_offer_engine_db()
        try:
            _record_result(connection)
        finally:
            connection.close()
        return summary
    except Exception as exc:
        connection = connect_offer_engine_db()
        try:
            _record_result(connection, f"{type(exc).__name__}: {exc}")
        finally:
            connection.close()
        raise


def main() -> None:
    if os.environ.get("SCENTHUNTER_OFFER_ENGINE_REFRESH_WORKER_ENABLED", "0").strip() != "1":
        print("Offer Engine refresh worker disabled", flush=True)
        return
    if os.environ.get("SCENTHUNTER_OFFER_ENGINE_AUTO_MIGRATE", "0").strip() == "1":
        raise RuntimeError("worker_refuses_automatic_schema_migration")
    # Refreshing is independent of the HTTP API. Keep the API and user-search
    # switches off during the pilot; this worker only writes the isolated DB.
    seed_canonical_catalog()
    interval = max(30, int(os.environ.get("SCENTHUNTER_OFFER_ENGINE_REFRESH_INTERVAL_SECONDS", "60")))
    print(f"Offer Engine refresh worker enabled; interval={interval}s", flush=True)
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        started = time.monotonic()
        try:
            print(f"Offer Engine refresh: {refresh_once()}", flush=True)
        except Exception as exc:
            print(f"Offer Engine refresh failed: {type(exc).__name__}: {exc}", flush=True)
        remaining = max(1.0, interval - (time.monotonic() - started))
        deadline = time.monotonic() + remaining
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))


if __name__ == "__main__":
    main()
