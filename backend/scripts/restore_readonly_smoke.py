"""Read-only catalog smoke test for a disposable Neon restore clone.

Phase 2 snapshots exercise the catalog API router. Historical 0006 snapshots
use read-only SQL compatibility checks because the Phase 2 ORM expects columns
that do not exist yet. The clone is never migrated or modified.
"""
from __future__ import annotations

import os
import sys
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

EXPECTED_DATABASE = os.environ.get("RESTORE_EXPECTED_DATABASE", "scenthunter_offerfirst")
SEARCH_QUERY = os.environ.get("RESTORE_SMOKE_SEARCH_QUERY", "Vulcan Feu")


def fail(message: str) -> None:
    raise RuntimeError(message)


def main() -> int:
    os.environ["SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL"] = "1"
    from app.db import make_engine
    from app.api.catalog_search import router

    engine = make_engine()
    try:
        with engine.connect() as conn:
            identity = conn.execute(text("""
                SELECT current_database() AS database_name,
                       current_user AS role_name,
                       current_setting('transaction_read_only') AS transaction_read_only,
                       r.rolsuper, r.rolcreatedb, r.rolcreaterole, r.rolreplication, r.rolbypassrls,
                       has_database_privilege(current_user, current_database(), 'CREATE') AS can_create_schema,
                       has_schema_privilege(current_user, 'public', 'CREATE') AS can_create_public_objects
                FROM pg_roles r
                WHERE r.rolname = current_user
            """)).mappings().one()
            print("DATABASE_IDENTITY", dict(identity))
            if identity["database_name"] != EXPECTED_DATABASE:
                fail(f"Connected to unexpected database: {identity['database_name']!r}")
            if identity["transaction_read_only"] != "on":
                fail("Connection is not transaction_read_only=on; refusing API smoke test")
            if any(identity[key] for key in ("rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls",
                                               "can_create_schema", "can_create_public_objects")):
                fail("Database role has elevated privileges; refusing API smoke test")

            schema_shape = conn.execute(text("""
                SELECT
                    EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'offers'
                          AND column_name = 'store_product_id'
                    ) AS offers_has_store_product_id,
                    EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'ingestion_raw'
                          AND column_name = 'store_product_id'
                    ) AS raw_has_store_product_id
            """)).mappings().one()
            print("CATALOG_SCHEMA_SHAPE", dict(schema_shape))
            if schema_shape["offers_has_store_product_id"] and schema_shape["raw_has_store_product_id"]:
                revision = "0007_catalog_identity"
            elif not schema_shape["offers_has_store_product_id"] and not schema_shape["raw_has_store_product_id"]:
                revision = "0006_postgres_ingestion_queue"
            else:
                fail("Restore clone has a partial Phase 2 store_product_id schema")

            if revision == "0006_postgres_ingestion_queue":
                # The historical restore clone predates Phase 2's additive
                # store_product_id columns. Do not migrate it: validate its
                # catalog and a known publishable offer using read-only SQL.
                counts = conn.execute(text("""
                    SELECT
                        (SELECT count(*) FROM fragrances) AS canonical_products,
                        (SELECT count(*) FROM product_variants) AS canonical_variants,
                        (SELECT count(*) FROM stores WHERE status = 'active') AS active_stores,
                        (SELECT count(*) FROM offers WHERE status = 'active') AS active_offers
                """)).mappings().one()
                print("CATALOG_STATUS_SQL", dict(counts))

                rows = conn.execute(text("""
                    SELECT b.name AS brand, f.name AS fragrance, s.name AS store,
                           s.domain, o.price, o.currency, o.url
                    FROM offers o
                    JOIN stores s ON s.id = o.store_id
                    JOIN ingestion_raw raw ON raw.id = o.ingestion_raw_id
                    JOIN product_variants pv ON pv.id = o.product_variant_id
                    JOIN fragrances f ON f.id = pv.fragrance_id
                    JOIN brands b ON b.id = f.brand_id
                    WHERE lower(f.name) LIKE :query
                      AND o.status = 'active'
                      AND s.status = 'active'
                      AND raw.status = 'promoted'
                      AND raw.product_variant_id = o.product_variant_id
                      AND raw.store_id = o.store_id
                      AND o.availability = 'in_stock'
                      AND o.price > 0
                      AND o.currency = 'EUR'
                      AND o.captured_at >= now() - interval '24 hours'
                      AND o.captured_at <= now()
                      AND (o.valid_until IS NULL OR o.valid_until > now())
                      AND raw.raw_payload ->> 'currency_explicit' = 'true'
                      AND EXISTS (
                          SELECT 1 FROM match_audit ma
                          WHERE ma.offer_id = o.id
                            AND ma.product_variant_id = o.product_variant_id
                      )
                    ORDER BY o.price, o.id
                    LIMIT 10
                """), {"query": f"%{SEARCH_QUERY.casefold()}%"}).mappings().all()
                valid_rows = []
                for row in rows:
                    host = (urlsplit(row["url"]).hostname or "").lower().rstrip(".")
                    domain = (row["domain"] or "").lower().rstrip(".")
                    if domain and (host == domain or host.endswith("." + domain)):
                        valid_rows.append(row)
                print("SEARCH_SQL_SUMMARY", {
                    "query": SEARCH_QUERY,
                    "count": len(valid_rows),
                    "offer_count": len(valid_rows),
                    "first_result": dict(valid_rows[0]) if valid_rows else None,
                })
                if not valid_rows:
                    fail(f"Read-only catalog search found no publishable offer for {SEARCH_QUERY!r}")
            elif revision != "0007_catalog_identity":
                fail(f"Unsupported restore-clone Alembic revision: {revision!r}")

        if revision == "0007_catalog_identity":
            app = FastAPI(title="ScentHunter restore read-only smoke")
            app.include_router(router)
            with TestClient(app) as client:
                status = client.get("/api/catalog/status")
                print("STATUS_HTTP", status.status_code)
                status.raise_for_status()
                status_payload = status.json()
                print("CATALOG_STATUS", status_payload)
                if status_payload.get("status") != "ready":
                    fail("Catalog status did not report ready")
                for field in ("canonical_products", "canonical_variants", "published_offers"):
                    if not isinstance(status_payload.get(field), int):
                        fail(f"Catalog status missing integer field: {field}")

                search = client.get("/api/catalog/search", params={"q": SEARCH_QUERY})
                print("SEARCH_HTTP", search.status_code)
                search.raise_for_status()
                search_payload = search.json()
                print("SEARCH_SUMMARY", {
                    "query": search_payload.get("query"),
                    "status": search_payload.get("status"),
                    "completed": search_payload.get("completed"),
                    "count": search_payload.get("count"),
                    "offer_count": search_payload.get("offer_count"),
                })
                if search_payload.get("status") != "completed" or search_payload.get("completed") is not True:
                    fail("Catalog search did not complete")
                results = search_payload.get("results")
                if not isinstance(results, list):
                    fail("Catalog search response has no results list")
                if search_payload.get("count", 0) < 1 or not results:
                    fail(f"Representative catalog search returned no product results for {SEARCH_QUERY!r}")
                if search_payload.get("offer_count", 0) < 1:
                    fail(f"Representative catalog search returned no published offers for {SEARCH_QUERY!r}")
                if not any(item.get("offers") for item in results):
                    fail("Search results contain no nested retailer offers")
                print("SEARCH_FIRST_RESULT", {
                    "brand": results[0].get("brand"),
                    "name": results[0].get("name"),
                    "offers": len(results[0].get("offers", [])),
                })

        print("RESTORE_READ_ONLY_SMOKE_RESULT=PASS")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"RESTORE_READ_ONLY_SMOKE_RESULT=FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
