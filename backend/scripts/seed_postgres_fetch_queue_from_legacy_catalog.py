"""Seed the PostgreSQL fetch queue from the existing retailer URL catalog.

Dry-run by default. The SQLite source is opened read-only. Applying only
creates/queues fetch work; it never copies stale SQLite prices into live offers.
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import URL, create_engine, make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.models import Store  # noqa: E402

STORE_CONFIG = {
    "bplatz": ("bplatz", "Bplatz", "en.bplatz.de", "DE"),
    "deloox": ("deloox-be", "Deloox", "www.deloox.be", "BE"),
    "sabina": ("sabina-es", "Sabina", "www.sabina.com", "ES"),
    "easycosmetic": ("easycosmetic-de", "Easycosmetic", "www.easycosmetic.de", "DE"),
    "parfumzentrum": ("parfumzentrum-de", "ParfumZentrum", "www.parfum-zentrum.de", "DE"),
}
BATCH_SIZE = 500


def source_engine(path: Path):
    path = path.expanduser().resolve(strict=True)
    url = URL.create(
        "sqlite+pysqlite", database=f"file:{path}",
        query={"mode": "ro", "uri": "true"},
    )
    return create_engine(url, pool_pre_ping=True)


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Create missing stores and enqueue fetch jobs")
    parser.add_argument("--confirm-target", help="Must exactly match the PostgreSQL database name")
    args = parser.parse_args()

    source = source_engine(args.source)
    target = target_engine()
    report = {"mode": "apply" if args.apply else "dry_run", "stores": {}, "queued_candidates": 0}
    try:
        with source.connect() as src:
            tables = set(src.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").scalars())
            required = {"store_urls"}
            if not required.issubset(tables):
                raise RuntimeError("Source is not the legacy retailer catalog: store_urls table missing")
            # Bound parameters are expanded safely by SQLAlchemy's expanding bind.
            from sqlalchemy import bindparam
            query = text("""
                SELECT store, url FROM store_urls
                WHERE active = 1 AND store IN :stores
                ORDER BY store, url
            """).bindparams(bindparam("stores", expanding=True))
            counts = dict.fromkeys(STORE_CONFIG, 0)
            for store_key, url in src.execute(query, {"stores": list(STORE_CONFIG)}):
                parsed = urlparse(str(url))
                expected_domain = STORE_CONFIG[store_key][2].lower()
                hostname = (parsed.hostname or "").lower()
                if (
                    parsed.scheme not in {"http", "https"}
                    or not hostname
                    or parsed.username is not None
                    or parsed.password is not None
                    or not (hostname == expected_domain or hostname.endswith("." + expected_domain))
                ):
                    continue
                counts[store_key] += 1
            report["stores"] = counts
            report["queued_candidates"] = sum(counts.values())

        with target.connect() as conn:
            db_name = conn.execute(text("SELECT current_database()")).scalar_one()
            if args.apply and args.confirm_target != db_name:
                raise ValueError("--confirm-target must exactly match target database name")
            existing_tables = set(__import__("sqlalchemy").inspect(conn).get_table_names())
            # A dry-run must remain useful before the queue migration is deployed:
            # it reports source coverage without requiring any destination writes/schema.
            if args.apply and "ingestion_queue_jobs" not in existing_tables:
                raise RuntimeError("PostgreSQL ingestion_queue_jobs table is missing; run the approved Alembic migration first")
            if args.apply:
                metadata = MetaData()
                queue = Table("ingestion_queue_jobs", metadata, autoload_with=conn)
                with Session(bind=conn) as session, session.begin():
                    stores = {}
                    for key, (slug, name, domain, country) in STORE_CONFIG.items():
                        store = session.scalar(select(Store).where(Store.slug == slug))
                        if store is None:
                            store = Store(
                                id=uuid.uuid4(), name=name, slug=slug, domain=domain,
                                country=country, currency="EUR", status="active",
                            )
                            session.add(store)
                            session.flush()
                        elif store.domain and store.domain.lower() != domain.lower():
                            raise RuntimeError(f"Store domain conflict for {slug}: {store.domain}")
                        elif store.status != "active":
                            raise RuntimeError(
                                f"Store {slug} is {store.status!r}; refusing to enqueue work "
                                "for an inactive or quarantined connector"
                            )
                        stores[key] = store.id

                from sqlalchemy import bindparam
                read_query = text("""
                    SELECT store, url FROM store_urls
                    WHERE active = 1 AND store IN :stores
                    ORDER BY store, url
                """).bindparams(bindparam("stores", expanding=True))
                batch = []
                inserted = 0
                with source.connect() as src, target.begin() as conn:
                    for store_key, url in src.execute(read_query, {"stores": list(STORE_CONFIG)}):
                        url = str(url).strip()
                        parsed = urlparse(url)
                        expected_domain = STORE_CONFIG[store_key][2].lower()
                        hostname = (parsed.hostname or "").lower()
                        if (
                            parsed.scheme not in {"http", "https"}
                            or not hostname
                            or parsed.username is not None
                            or parsed.password is not None
                            or not (hostname == expected_domain or hostname.endswith("." + expected_domain))
                        ):
                            continue
                        slug = STORE_CONFIG[store_key][0]
                        store_id = stores[store_key]
                        payload = {"store_id": str(store_id), "external_product_id": url}
                        import hashlib, json
                        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
                        batch.append({
                            "id": uuid.uuid4(), "stage": "fetch", "payload": payload,
                            "dedupe_key": hashlib.sha256(serialized.encode()).hexdigest(),
                            "status": "queued", "attempts": 0, "max_attempts": 5,
                            "available_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                            "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                        })
                        if len(batch) >= BATCH_SIZE:
                            result = conn.execute(pg_insert(queue).values(batch).on_conflict_do_nothing(
                                index_elements=[queue.c.stage, queue.c.dedupe_key],
                                index_where=text("status IN ('queued','running')"),
                            ))
                            inserted += max(0, result.rowcount or 0)
                            batch.clear()
                    if batch:
                        result = conn.execute(pg_insert(queue).values(batch).on_conflict_do_nothing(
                            index_elements=[queue.c.stage, queue.c.dedupe_key],
                            index_where=text("status IN ('queued','running')"),
                        ))
                        inserted += max(0, result.rowcount or 0)
                report["new_jobs_inserted"] = inserted
                report["destination_written"] = True
            report["target_database"] = db_name
        print(report)
    finally:
        source.dispose()
        target.dispose()


if __name__ == "__main__":
    main()
