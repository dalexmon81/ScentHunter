"""Dry-run-first importer for the canonical Phase 2 SQLite catalog.

The source is always opened read-only. The destination is accepted only from
SCENTHUNTER_MIGRATION_TARGET_DATABASE_URL and must be PostgreSQL. No retailer
discovery/hydration database is supported by this importer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from decimal import Decimal
from uuid import UUID

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.models import Base  # noqa: E402

TABLE_ORDER = (
    "brands", "fragrances", "product_variants", "stores",
    "legacy_product_id_map", "legacy_variant_id_map", "ingestion_raw",
    "offers", "price_history", "match_audit", "ingestion_runs",
)
EXPECTED_REVISION = "0003_store_domain"


def open_source_read_only(source_path: Path):
    source_path = source_path.expanduser().resolve(strict=True)
    if not source_path.is_file():
        raise ValueError("Source must be an existing SQLite database file.")
    url = URL.create(
        "sqlite+pysqlite", database=f"file:{source_path}",
        query={"mode": "ro", "uri": "true"},
    )
    return create_engine(url, pool_pre_ping=True)


def open_migration_target(environ=None):
    env = os.environ if environ is None else environ
    raw_url = (env.get("SCENTHUNTER_MIGRATION_TARGET_DATABASE_URL") or "").strip()
    if not raw_url:
        raise ValueError(
            "Set SCENTHUNTER_MIGRATION_TARGET_DATABASE_URL to a dedicated migration target."
        )
    try:
        url = make_url(raw_url)
    except Exception:
        raise ValueError("Migration target URL is invalid.") from None
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    if url.drivername != "postgresql+psycopg":
        raise ValueError("Migration target must use PostgreSQL with psycopg 3.")
    return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=0)


def _validate_schema(connection, label):
    inspector = inspect(connection)
    missing = sorted(set(TABLE_ORDER) - set(inspector.get_table_names()))
    if missing:
        raise RuntimeError(f"{label} is missing canonical catalog tables: {missing}")
    for name in TABLE_ORDER:
        expected = {column.name for column in Base.metadata.tables[name].columns}
        actual = {column["name"] for column in inspector.get_columns(name)}
        if expected != actual:
            raise RuntimeError(
                f"{label} schema mismatch for {name}: "
                f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
            )


def _equivalent_value(left, right):
    # SQLite commonly returns timezone-naive values for DateTime(timezone=True),
    # while PostgreSQL returns aware UTC values. Compare the same instant.
    if isinstance(left, datetime) and isinstance(right, datetime):
        if left.tzinfo is None:
            left = left.replace(tzinfo=timezone.utc)
        if right.tzinfo is None:
            right = right.replace(tzinfo=timezone.utc)
        return left.astimezone(timezone.utc) == right.astimezone(timezone.utc)
    return left == right


def _same_row(existing, incoming, columns):
    return all(
        _equivalent_value(existing[column], incoming[column])
        for column in columns
    )


def _canonical_value(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


def _update_checksum(digest, row, columns):
    canonical = {column: _canonical_value(row[column]) for column in columns}
    digest.update(json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8"))
    digest.update(b"\\n")


def _table_checksum(connection, table):
    columns = [column.name for column in table.columns]
    pk = list(table.primary_key.columns)[0]
    digest = hashlib.sha256()
    for row in connection.execute(select(table).order_by(pk)).mappings():
        _update_checksum(digest, row, columns)
    return digest.hexdigest()


def inspect_and_import(source_path: Path, target_engine, *, apply=False, confirm_target=None):
    """Compare source and destination; apply only inside one destination transaction."""
    if target_engine.dialect.name != "postgresql":
        raise ValueError("Migration destination must be PostgreSQL.")
    with target_engine.connect() as target_connection:
        _validate_schema(target_connection, "PostgreSQL target")
        revision = target_connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        if revision != EXPECTED_REVISION:
            raise RuntimeError(
                f"Target Alembic revision must be {EXPECTED_REVISION}; found {revision}."
            )
        database_name = target_connection.execute(
            text("SELECT current_database()")
        ).scalar_one()
        if apply and confirm_target != database_name:
            raise ValueError(
                "For apply, --confirm-target must exactly match the PostgreSQL database name."
            )

    source_engine = open_source_read_only(source_path)
    report = {
        "status": "dry_run", "source": source_path.name,
        "target_database": database_name, "target_dialect": "postgresql",
        "alembic_revision": revision, "tables": {},
        "source_modified": False, "destination_written": False,
    }
    try:
        with source_engine.connect() as source_connection:
            _validate_schema(source_connection, "SQLite source")
            source_revision = source_connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            if source_revision != EXPECTED_REVISION:
                raise RuntimeError(
                    f"Source Alembic revision must be {EXPECTED_REVISION}; "
                    f"found {source_revision}."
                )
            report["source_alembic_revision"] = source_revision
            violations = source_connection.exec_driver_sql(
                "PRAGMA foreign_key_check"
            ).fetchall()
            if violations:
                raise RuntimeError(
                    f"SQLite source has {len(violations)} foreign-key violations."
                )

            with target_engine.begin() as target_connection:
                for table_name in TABLE_ORDER:
                    table = Base.metadata.tables[table_name]
                    primary_key = list(table.primary_key.columns)
                    if len(primary_key) != 1:
                        raise RuntimeError(
                            f"Importer requires a single-column primary key: {table_name}"
                        )
                    pk = primary_key[0]
                    columns = [column.name for column in table.columns]
                    source_count = source_connection.execute(
                        select(func.count()).select_from(table)
                    ).scalar_one()
                    target_before = target_connection.execute(
                        select(func.count()).select_from(table)
                    ).scalar_one()
                    would_insert = 0
                    already_present = 0
                    source_digest = hashlib.sha256()
                    for row in source_connection.execute(
                        select(table).order_by(pk)
                    ).mappings():
                        _update_checksum(source_digest, row, columns)
                        incoming = dict(row)
                        existing = target_connection.execute(
                            select(table).where(pk == incoming[pk.name])
                        ).mappings().one_or_none()
                        if existing is None:
                            would_insert += 1
                            if apply:
                                target_connection.execute(table.insert().values(**incoming))
                        else:
                            if not _same_row(existing, incoming, columns):
                                raise RuntimeError(
                                    f"Conflicting existing primary key in {table_name}; "
                                    "destination was not overwritten."
                                )
                            already_present += 1

                    target_checksum_checked = _table_checksum(target_connection, table)
                    source_checksum = source_digest.hexdigest()
                    checksums_match = source_checksum == target_checksum_checked
                    if apply and not checksums_match:
                        raise RuntimeError(
                            f"Post-import checksum mismatch for {table_name}; "
                            "the destination transaction will be rolled back."
                        )
                    report["tables"][table_name] = {
                        "source_rows": source_count,
                        "target_rows_before": target_before,
                        "would_insert": would_insert,
                        "already_present_identical": already_present,
                        "source_sha256": source_checksum,
                        "target_sha256_checked": target_checksum_checked,
                        "target_sha256_after_import": target_checksum_checked if apply else None,
                        "checksums_match_after_import": checksums_match if apply else None,
                    }

        report["status"] = "applied" if apply else "dry_run"
        report["destination_written"] = bool(apply)
        return report
    finally:
        source_engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path,
                        help="canonical SQLite database file; opened read-only")
    parser.add_argument("--apply", action="store_true",
                        help="apply missing rows; default is a read-only dry run")
    parser.add_argument("--confirm-target",
                        help="required with --apply; exact PostgreSQL database name")
    args = parser.parse_args(argv)

    if args.confirm_target and not args.apply:
        parser.error("--confirm-target is meaningful only together with --apply")

    target_engine = open_migration_target()
    try:
        report = inspect_and_import(
            args.source, target_engine, apply=args.apply,
            confirm_target=args.confirm_target,
        )
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return 0
    finally:
        target_engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
