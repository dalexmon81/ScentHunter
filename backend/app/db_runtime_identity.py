"""Safe runtime identity logging for SQLite and PostgreSQL catalog connections."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import PurePosixPath


def configuration_source(environ=None):
    env = os.environ if environ is None else environ
    if env.get("SCENTHUNTER_CATALOG_DATABASE_URL"):
        return "SCENTHUNTER_CATALOG_DATABASE_URL"
    if env.get("SCENTHUNTER_DATABASE_URL"):
        return "SCENTHUNTER_DATABASE_URL"
    return "application_default"


def opened_at_utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _database_identity(connection):
    dialect = connection.dialect.name
    if dialect == "sqlite":
        rows = connection.exec_driver_sql("PRAGMA database_list").fetchall()
        return [
            (str(row[1] or "main"), str(row[2] or ""))
            for row in rows
        ]
    if dialect == "postgresql":
        row = connection.exec_driver_sql(
            "SELECT current_database(), current_schema()"
        ).one()
        return [(str(row[0]), str(row[1] or ""))]
    raise RuntimeError(f"Unsupported database identity dialect: {dialect}")


def log_runtime_database_identity(
    connection, *, event_name, service_name, config_source, opened_at=None,
):
    """Log a masked identity derived from the exact live SQLAlchemy connection."""
    for database_name, database_location in _database_identity(connection):
        if connection.dialect.name == "sqlite":
            basename = PurePosixPath(database_location).name or "database"
            masked_location = ".../" + basename if database_location else "<memory-or-empty>"
            identity_material = database_name + "\\0" + database_location
        else:
            masked_location = database_location or "<default-schema>"
            identity_material = connection.dialect.name + "\\0" + database_name + "\\0" + database_location
        fingerprint = hashlib.sha256(identity_material.encode("utf-8")).hexdigest()[:16]
        print(
            "PHASE2_RUNTIME_DATABASE "
            f"event={event_name} pid={os.getpid()} service={service_name} "
            f"config_source={config_source} dialect={connection.dialect.name} "
            f"database_name={database_name} database_location={masked_location} "
            f"database_id=sha256:{fingerprint} "
            f"connection_opened_at={opened_at or opened_at_utc()}",
            flush=True,
        )
