"""Read-only verification of the live public catalog PostgreSQL runtime.

This script intentionally refuses SQLite and never prints connection details.
"""
from __future__ import annotations

import json
import os
import urllib.request

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from app.db import database_url, make_engine


def main() -> None:
    configured_key = next(
        (key for key in ("SCENTHUNTER_CATALOG_DATABASE_URL", "SCENTHUNTER_DATABASE_URL")
         if os.environ.get(key)),
        None,
    )
    if not configured_key:
        raise SystemExit(
            "FAIL: no public catalog PostgreSQL URL configured; app.db would fall back to SQLite"
        )

    required = os.environ.get("SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL", "").strip().lower()
    if required not in {"1", "true", "yes", "on"}:
        raise SystemExit(
            "FAIL: SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL is not enabled; SQLite fallback is not blocked"
        )

    url = make_url(database_url())
    if url.get_backend_name() != "postgresql":
        raise SystemExit("FAIL: configured public catalog database is not PostgreSQL")
    if url.database != "scenthunter_offerfirst":
        raise SystemExit("FAIL: public catalog URL targets an unexpected database")

    engine = make_engine()
    try:
        with engine.connect() as connection:
            database = connection.execute(text("SELECT current_database()")).scalar_one()
            if database != "scenthunter_offerfirst":
                raise SystemExit("FAIL: connected PostgreSQL database identity mismatch")
            tables = set(inspect(connection).get_table_names())
            required_tables = {"brands", "fragrances", "product_variants", "offers", "alembic_version"}
            missing = sorted(required_tables - tables)
            if missing:
                raise SystemExit("FAIL: PostgreSQL catalog schema is incomplete: " + ", ".join(missing))
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if revision != "0006_postgres_ingestion_queue":
                raise SystemExit("FAIL: PostgreSQL schema is not at the expected Alembic revision")
            counts = {}
            for table in ("brands", "fragrances", "product_variants", "offers"):
                counts[table] = connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
    finally:
        engine.dispose()

    request = urllib.request.Request(
        "http://127.0.0.1:8080/api/catalog/status",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            if response.status != 200:
                raise SystemExit(f"FAIL: public catalog status endpoint returned HTTP {response.status}")
            status_payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise SystemExit(f"FAIL: public catalog status endpoint unavailable: {type(exc).__name__}") from None

    print(json.dumps({
        "status": "PASS",
        "database": database,
        "configured_env_key": configured_key,
        "postgresql_required": True,
        "alembic_revision": revision,
        "catalog_rows": counts,
        "public_status_endpoint": "HTTP 200",
        "public_status_keys": sorted(status_payload) if isinstance(status_payload, dict) else [],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
