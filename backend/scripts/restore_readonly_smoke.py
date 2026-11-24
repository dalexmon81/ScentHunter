"""Read-only application smoke test for a disposable Neon restore clone.

This intentionally builds a tiny FastAPI app from the catalog read router only.
It does not import backend.main, whose startup hooks can launch discovery,
hydration and bootstrap workers.
"""
from __future__ import annotations

import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

EXPECTED_DATABASE = os.environ.get("RESTORE_EXPECTED_DATABASE", "scenthunter_offerfirst")
SEARCH_QUERY = os.environ.get("RESTORE_SMOKE_SEARCH_QUERY", "Dior")


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

            writable = conn.execute(text("""
                SELECT n.nspname AS table_schema, c.relname AS table_name,
                       p.privilege
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                CROSS JOIN LATERAL (VALUES
                    ('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE'),
                    ('REFERENCES'), ('TRIGGER')
                ) AS p(privilege)
                WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
                  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                  AND has_table_privilege(current_user, c.oid, p.privilege)
                LIMIT 1
            """)).mappings().first()
            if writable:
                fail(f"Role has table write privilege: {dict(writable)}")

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
            if not isinstance(search_payload.get("results"), list):
                fail("Catalog search response has no results list")

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
