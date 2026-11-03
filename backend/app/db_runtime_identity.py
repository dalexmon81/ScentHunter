"""Safe database identity logging from the exact Phase 2 connection."""
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


def log_runtime_database_identity(
    connection, *, event_name, service_name, config_source, opened_at=None,
):
    """Log a masked identity using the caller's already-open connection."""
    backend = connection.dialect.name
    if backend == "sqlite":
        rows = connection.exec_driver_sql("PRAGMA database_list").fetchall()
        identities = []
        for row in rows:
            database_name = str(row[1] or "main")
            database_path = str(row[2] or "")
            basename = PurePosixPath(database_path).name if database_path else ""
            identities.append((database_name, ".../" + basename if basename else "<memory-or-empty>"))
    elif backend == "postgresql":
        row = connection.exec_driver_sql(
            "SELECT current_database(), current_schema()"
        ).one()
        identities = [(str(row[0]), str(row[1] or "public"))]
    else:
        raise RuntimeError("Unsupported Phase 2 database dialect for identity logging.")

    for database_name, safe_location in identities:
        fingerprint = hashlib.sha256(
            (backend + "\\0" + database_name + "\\0" + safe_location).encode("utf-8")
        ).hexdigest()[:16]
        print(
            "PHASE2_RUNTIME_DATABASE "
            f"event={event_name} pid={os.getpid()} service={service_name} "
            f"config_source={config_source} dialect={backend} "
            f"database_name={database_name} database_path={safe_location} "
            f"database_id=sha256:{fingerprint} "
            f"connection_opened_at={opened_at or opened_at_utc()}",
            flush=True,
        )
