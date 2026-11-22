"""Read-only preflight for the PostgreSQL legacy URL queue seed."""
from __future__ import annotations

import json
import os

from sqlalchemy import bindparam, create_engine, inspect, text
from sqlalchemy.engine import make_url

STORE_CONFIG = {
    "bplatz": ("bplatz", "Bplatz", "bplatz.de", "DE"),
    "deloox-be": ("deloox-be", "Deloox Belgium", "www.deloox.be", "BE"),
    "deloox-nl": ("deloox-nl", "Deloox Netherlands", "www.deloox.nl", "NL"),
    "deloox-com": ("deloox-com", "Deloox International", "www.deloox.com", None),
    "deloox-lu": ("deloox-lu", "Deloox Luxembourg", "www.deloox.lu", "LU"),
    "deloox-es": ("deloox-es", "Deloox Spain", "www.deloox.es", "ES"),
    "sabina": ("sabina-es", "Sabina", "www.sabina.com", "ES"),
    "easycosmetic": ("easycosmetic-de", "Easycosmetic", "www.easycosmetic.de", "DE"),
    "parfumzentrum": ("parfumzentrum-de", "ParfumZentrum", "www.parfum-zentrum.de", "DE"),
}


def target_engine():
    raw = os.environ.get("SCENTHUNTER_MIGRATION_TARGET_DATABASE_URL", "").strip()
    if not raw:
        raise ValueError("SCENTHUNTER_MIGRATION_TARGET_DATABASE_URL is required")
    url = make_url(raw)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    if url.drivername != "postgresql+psycopg":
        raise ValueError("Target must be PostgreSQL using psycopg 3")
    return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=0)


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
