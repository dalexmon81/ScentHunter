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
                folded_brand = product.brand.strip().casefold()
                folded_name = product.name.strip().casefold()
                # Catalog variant aliases often repeat the full canonical
                # brand + product name. Repeating them in the search query
                # breaks exact priority matching and can make retailer
                # discovery miss an otherwise valid product query.
                alias_already_contains_identity = (
                    folded_brand in folded_label and folded_name in folded_label
                )
                if "limited edition" in folded_label and "limited edition" not in product.name.casefold():
                    parts.append("Limited Edition")
                elif not alias_already_contains_identity and folded_label not in {folded_name, folded_brand}:
                    parts.append(label)
            parts.append(f"{int(variant.size_ml)} ml")
            query = " ".join(part.strip() for part in parts if part and part.strip())
            key = query.casefold()
            if query and key not in seen:
                seen.add(key)
                queries.append(query)
    return queries


def build_product_query_fallbacks(catalog: Any, primary_query: str) -> list[str]:
    """Build broader discovery queries for the exact catalog variant.

    Retailer search engines often fail on brand-qualified or size-qualified
    phrases even when the exact product page is indexed. Broader queries are
    discovery only: fetched product-page facts and CanonicalMatcher still
    decide product identity, exact bottle size, price and stock.
    """
    target = str(primary_query or "").strip().casefold()
    for product in catalog.all_products():
        for variant in product.variants:
            if variant.size_ml is None:
                continue
            parts = [product.brand, product.name]
            if variant.label:
                label = variant.label.strip()
                folded_label = label.casefold()
                folded_brand = product.brand.strip().casefold()
                folded_name = product.name.strip().casefold()
                alias_already_contains_identity = (
                    folded_brand in folded_label and folded_name in folded_label
                )
                if "limited edition" in folded_label and "limited edition" not in product.name.casefold():
                    parts.append("Limited Edition")
                elif not alias_already_contains_identity and folded_label not in {folded_name, folded_brand}:
                    parts.append(label)
            parts.append(f"{int(variant.size_ml)} ml")
            exact = " ".join(part.strip() for part in parts if part and part.strip())
            if exact.casefold() != target:
                continue
            candidates = [
                f"{product.name} {int(variant.size_ml)} ml",
                f"{product.brand} {product.name}",
                product.name,
            ]
            output = []
            seen = {target}
            for item in candidates:
                normalized = " ".join(str(item or "").split())
                key = normalized.casefold()
                if normalized and key not in seen:
                    seen.add(key)
                    output.append(normalized)
            return output
    return []

def prioritize_product_queries(queries: list[str], priority_queries: list[str]) -> list[str]:
    """Move explicitly requested pilot queries to the front without losing catalog coverage."""
    priority = {value.strip().casefold(): index for index, value in enumerate(priority_queries) if value.strip()}
    return [
        query for _index, query in sorted(
            enumerate(queries),
            key=lambda item: (priority.get(item[1].casefold(), len(priority)), item[0]),
        )
    ]


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
    priority_queries = [
        item.strip()
        for item in os.environ.get("SCENTHUNTER_OFFER_ENGINE_REFRESH_PRIORITY_QUERIES", "").split(";")
        if item.strip()
    ]
    queries = prioritize_product_queries(queries, priority_queries)
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
        fallback_queries = build_product_query_fallbacks(catalog, query)
        discovery_queries = [query, *fallback_queries]
        results = [(item_query, run_offer_engine(item_query)) for item_query in discovery_queries]
        # Keep each retailer/query outcome visible. A broader search phrase is
        # only a discovery aid; the product-page verifier and canonical matcher
        # still reject wrong products, wrong sizes, unknown stock and bad prices.
        connector_reports = [
            {
                "query": item_query,
                "retailer": connector.retailer,
                "status": connector.status,
                "listings_seen": connector.listings_seen,
                "observations_written": connector.observations_written,
                "offers_published": connector.offers_published,
                "unresolved": connector.unresolved,
                "errors": connector.errors[:8],
                "unresolved_samples": connector.unresolved_samples[:5],
            }
            for item_query, result in results
            for connector in result.connectors
        ]
        per_retailer = {}
        for report in connector_reports:
            per_retailer.setdefault(report["retailer"], []).append(report["status"])
        failed_connectors = sorted(
            retailer for retailer, statuses in per_retailer.items()
            if statuses and all(status == "failed" for status in statuses)
        )
        partial_connectors = sorted(
            retailer for retailer, statuses in per_retailer.items()
            if any(status in {"failed", "partial"} for status in statuses)
            and retailer not in failed_connectors
        )
        summary = {
            "query": query,
            "discovery_queries": discovery_queries,
            "connectors": len(per_retailer),
            "listings_seen": sum(result.listings_seen for _, result in results),
            "observations_written": sum(result.observations_written for _, result in results),
            "offers_published": sum(result.offers_published for _, result in results),
            "failed_connectors": failed_connectors,
            "partial_connectors": partial_connectors,
            "connector_reports": connector_reports,
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
