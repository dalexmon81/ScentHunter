"""Independent, rate-limited Offer Engine catalog refresh worker.

The worker is opt-in and never runs in the HTTP request path. It rotates through
canonical products, asks configured retailer connectors to discover them, and
persists observations through the existing verification policy. It deliberately
does not infer variants or publish unverified observations.
"""
from __future__ import annotations

import os
import signal
import time
from typing import Any

from .runtime import CATALOG_PATH, connect_offer_engine_db, run_offer_engine, seed_canonical_catalog
try:
    from scenthunter_next_engine.catalog_repository import CatalogRepository
except ModuleNotFoundError:
    from backend.scenthunter_next_engine.catalog_repository import CatalogRepository


def build_product_queries(catalog: Any) -> list[str]:
    """Return one deterministic retailer query per canonical product with variants."""
    queries: list[str] = []
    seen: set[str] = set()
    for product in catalog.all_products():
        if not product.variants:
            continue
        query = " ".join(part.strip() for part in (product.brand, product.name) if part and part.strip())
        key = query.casefold()
        if query and key not in seen:
            seen.add(key)
            queries.append(query)
    return queries


def _ensure_scheduler_row(connection: Any) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO sh_refresh_scheduler(id, product_cursor) VALUES (1, 0)"
    )
    connection.commit()


def _next_query(connection: Any, queries: list[str]) -> str:
    if not queries:
        raise RuntimeError("offer_engine_catalog_has_no_refreshable_products")
    _ensure_scheduler_row(connection)
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute(
            "SELECT product_cursor FROM sh_refresh_scheduler WHERE id=1"
        ).fetchone()
        cursor = int(row[0] or 0) % len(queries)
        connection.execute(
            """UPDATE sh_refresh_scheduler
                  SET product_cursor=?, last_started_at=CURRENT_TIMESTAMP,
                      last_error=NULL
                WHERE id=1""",
            ((cursor + 1) % len(queries),),
        )
        connection.commit()
        return queries[cursor]
    except Exception:
        connection.rollback()
        raise


def _record_result(connection: Any, error: str | None = None) -> None:
    connection.execute(
        """UPDATE sh_refresh_scheduler
              SET last_finished_at=CURRENT_TIMESTAMP, last_error=?
            WHERE id=1""",
        (error[:1000] if error else None,),
    )
    connection.commit()


def refresh_once() -> dict[str, Any]:
    """Refresh one canonical product across configured independent connectors."""
    catalog = CatalogRepository.from_file(CATALOG_PATH)
    queries = build_product_queries(catalog)
    connection = connect_offer_engine_db()
    try:
        # A missing migration is a hard failure; the worker must never silently
        # create production schema or alter the migration safety switches.
        connection.execute("SELECT product_cursor FROM sh_refresh_scheduler LIMIT 1")
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
    if os.environ.get("SCENTHUNTER_OFFER_ENGINE_API_ENABLED", "0").strip() != "1":
        raise RuntimeError("worker_requires_offer_engine_api_enablement_gate")
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
