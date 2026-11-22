"""Read-only preflight for the PostgreSQL legacy URL queue seed."""
from __future__ import annotations

import json
from sqlalchemy import bindparam, inspect, text

from scripts.seed_postgres_fetch_queue_from_legacy_catalog import (
    STORE_CONFIG,
    target_engine,
)


def main() -> None:
    engine = target_engine()
    try:
        with engine.connect() as connection:
            database = connection.execute(
                text("SELECT current_database()")
            ).scalar_one()
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            report = {
                "database": database,
                "alembic_revision": None,
                "stores_table_present": "stores" in tables,
                "queue_table_present": "ingestion_queue_jobs" in tables,
                "expected_store_count": len(STORE_CONFIG),
                "existing_stores": [],
                "missing_store_slugs": [],
                "domain_conflicts": [],
                "inactive_stores": [],
                "queue_counts_by_stage_status": [],
                "safe_to_apply_preflight": False,
            }

            if "alembic_version" in tables:
                report["alembic_revision"] = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()

            if "stores" in tables:
                slugs = [item[0] for item in STORE_CONFIG.values()]
                rows = connection.execute(
                    text("""
                        SELECT slug, name, domain, country, status
                        FROM stores WHERE slug IN :slugs ORDER BY slug
                    """).bindparams(bindparam("slugs", expanding=True)),
                    {"slugs": slugs},
                ).mappings().all()
                by_slug = {row["slug"]: dict(row) for row in rows}
                report["existing_stores"] = list(by_slug.values())

                for _key, (slug, name, domain, country) in STORE_CONFIG.items():
                    row = by_slug.get(slug)
                    if row is None:
                        report["missing_store_slugs"].append(slug)
                        continue
                    actual_domain = (row["domain"] or "").strip().lower().rstrip(".")
                    expected_domain = domain.strip().lower().rstrip(".")
                    if actual_domain and actual_domain != expected_domain:
                        report["domain_conflicts"].append({
                            "slug": slug,
                            "expected_domain": expected_domain,
                            "actual_domain": actual_domain,
                        })
                    if row["status"] != "active":
                        report["inactive_stores"].append({
                            "slug": slug, "status": row["status"],
                        })

            if "ingestion_queue_jobs" in tables:
                columns = {column["name"] for column in inspector.get_columns("ingestion_queue_jobs")}
                if {"stage", "status"}.issubset(columns):
                    report["queue_counts_by_stage_status"] = [
                        dict(row) for row in connection.execute(text("""
                            SELECT stage, status, count(*) AS jobs
                            FROM ingestion_queue_jobs
                            GROUP BY stage, status
                            ORDER BY stage, status
                        """)).mappings().all()
                    ]

            report["safe_to_apply_preflight"] = bool(
                report["stores_table_present"]
                and report["queue_table_present"]
                and not report["domain_conflicts"]
                and not report["inactive_stores"]
            )
            print(json.dumps(report, sort_keys=True, default=str))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
