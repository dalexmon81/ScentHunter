"""Seed the PostgreSQL fetch queue from the existing retailer URL catalog.

Dry-run by default. The SQLite source is opened read-only. Applying only
creates/queues fetch work; it never copies stale SQLite prices into live offers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import MetaData, Table, bindparam, inspect, select, text
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
# The canonical Deloox store row is deloox-be. Other Deloox storefronts
# require their own Store rows/domains before their offers can pass the
# public-search URL gate; do not enqueue them under the Belgian store identity.
STORE_URL_DOMAINS = {
    "bplatz": ("en.bplatz.de",),
    "deloox": ("www.deloox.be",),
    "sabina": ("www.sabina.com",),
    "easycosmetic": ("www.easycosmetic.de",),
    "parfumzentrum": ("www.parfum-zentrum.de",),
}
BATCH_SIZE = 500


def is_allowed_product_url(url: str, expected_domain: str | tuple[str, ...]) -> bool:
    """Accept only HTTP(S) product URLs hosted by a registered retailer domain."""
    parsed = urlparse(str(url).strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    domains = (expected_domain,) if isinstance(expected_domain, str) else tuple(expected_domain)
    allowed = tuple(str(domain).strip().lower().rstrip(".") for domain in domains if str(domain).strip())
    return bool(
        parsed.scheme.lower() in {"http", "https"}
        and hostname
        and parsed.username is None
        and parsed.password is None
        and allowed
        and any(hostname == domain or hostname.endswith("." + domain) for domain in allowed)
    )


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


def _read_candidates(connection):
    """Read and validate one stable candidate snapshot from the source DB."""
    tables = set(connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).scalars())
    if "store_urls" not in tables:
        raise RuntimeError(
            "Source is not the legacy retailer catalog: store_urls table missing"
        )

    query = text("""
        SELECT store, url FROM store_urls
        WHERE active = 1 AND store IN :stores
        ORDER BY store, url
    """).bindparams(bindparam("stores", expanding=True))

    accepted = []
    rejected = dict.fromkeys(STORE_CONFIG, 0)
    rejected_domains = {store_key: {} for store_key in STORE_CONFIG}
    seen = set()
    duplicate_count = 0
    for store_key, raw_url in connection.execute(
        query, {"stores": list(STORE_CONFIG)}
    ):
        url = str(raw_url or "").strip()
        domains = STORE_URL_DOMAINS[store_key]
        if not is_allowed_product_url(url, domains):
            rejected[store_key] += 1
            hostname = (urlparse(url).hostname or "(missing)").lower().rstrip(".")
            rejected_domains[store_key][hostname] = (
                rejected_domains[store_key].get(hostname, 0) + 1
            )
            continue
        candidate = (store_key, url)
        if candidate in seen:
            duplicate_count += 1
            continue
        seen.add(candidate)
        accepted.append(candidate)

    accepted.sort(key=lambda item: (item[0], item[1]))
    return accepted, rejected, duplicate_count, rejected_domains


def _queue_rows(connection, queue, candidates, stores):
    """Insert queue jobs using the caller's transaction and return new row count."""
    inserted = 0
    now = datetime.now(timezone.utc)
    for offset in range(0, len(candidates), BATCH_SIZE):
        batch = []
        for store_key, url in candidates[offset:offset + BATCH_SIZE]:
            payload = {
                "store_id": str(stores[store_key]),
                "external_product_id": url,
            }
            serialized = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
            digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
            batch.append({
                "id": uuid.uuid4(),
                "stage": "fetch",
                "payload": payload,
                "dedupe_key": digest,
                "status": "queued",
                "attempts": 0,
                "max_attempts": 5,
                "available_at": now,
                "created_at": now,
            })
        if not batch:
            continue
        result = connection.execute(
            pg_insert(queue).values(batch).on_conflict_do_nothing(
                index_elements=[queue.c.stage, queue.c.dedupe_key],
                index_where=text("status IN ('queued','running')"),
            )
        )
        inserted += max(0, result.rowcount or 0)
    return inserted


def _apply_candidates(connection, candidates):
    """Create/lock Store rows and enqueue candidates on one outer transaction."""
    metadata = MetaData()
    queue = Table("ingestion_queue_jobs", metadata, autoload_with=connection)
    stores = {}
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        for key, (slug, name, domain, country) in STORE_CONFIG.items():
            store = session.scalar(
                select(Store).where(Store.slug == slug).with_for_update()
            )
            if store is None:
                store = Store(
                    id=uuid.uuid4(), name=name, slug=slug, domain=domain,
                    country=country, currency="EUR", status="active",
                )
                session.add(store)
                session.flush()
            else:
                if store.domain and store.domain.lower() != domain.lower():
                    raise RuntimeError(
                        f"Store domain conflict for {slug}: {store.domain}"
                    )
                # Existing placeholder Store rows may have been created before
                # a connector domain was assigned. Fill only missing metadata;
                # never overwrite a conflicting non-empty domain.
                if not store.domain:
                    store.domain = domain
                if not store.country:
                    store.country = country
                if store.status != "active":
                    raise RuntimeError(
                        f"Store {slug} is {store.status!r}; refusing "
                        "to enqueue work for an inactive or quarantined connector"
                    )
            stores[key] = store.id
        session.flush()
        inserted = _queue_rows(connection, queue, candidates, stores)
        # Release only the Session savepoint; the caller owns the outer
        # transaction and commits Store rows and queue jobs together.
        session.commit()
        return inserted



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--apply", action="store_true",
        help="Create missing stores and enqueue fetch jobs",
    )
    parser.add_argument(
        "--confirm-target",
        help="Must exactly match the PostgreSQL database name",
    )
    args = parser.parse_args()

    source = source_engine(args.source)
    target = target_engine()
    report = {
        "mode": "apply" if args.apply else "dry_run",
        "stores": {},
        "rejected_by_store": {},
        "duplicate_candidates": 0,
        "queued_candidates": 0,
        "new_jobs_inserted": 0,
        "destination_written": False,
    }
    try:
        # SQLite read transaction gives dry-run and apply a consistent view.
        with source.connect() as src:
            with src.begin():
                candidates, rejected, duplicate_count, rejected_domains = _read_candidates(src)
        counts = dict.fromkeys(STORE_CONFIG, 0)
        for store_key, _url in candidates:
            counts[store_key] += 1
        report.update({
            "stores": counts,
            "rejected_by_store": rejected,
            "rejected_domains_by_store": rejected_domains,
            "duplicate_candidates": duplicate_count,
            "queued_candidates": len(candidates),
        })

        # One PostgreSQL transaction includes Store creation and every queue
        # insert. Any failure rolls back both, so no orphan Store rows remain.
        with target.begin() as conn:
            db_name = conn.execute(
                text("SELECT current_database()")
            ).scalar_one()
            report["target_database"] = db_name
            if args.apply and args.confirm_target != db_name:
                raise ValueError(
                    "--confirm-target must exactly match target database name"
                )

            existing_tables = set(inspect(conn).get_table_names())
            if args.apply:
                required = {"ingestion_queue_jobs", "stores"}
                missing = required - existing_tables
                if missing:
                    raise RuntimeError(
                        "Required PostgreSQL tables are missing: "
                        + ", ".join(sorted(missing))
                        + "; run the approved Alembic migration first"
                    )

                inserted = _apply_candidates(conn, candidates)

                report["new_jobs_inserted"] = inserted
                report["destination_written"] = True
            # Dry-run deliberately checks the database identity but does not
            # require the queue schema to have been applied.
        print(report)
    finally:
        source.dispose()
        target.dispose()


if __name__ == "__main__":
    main()
