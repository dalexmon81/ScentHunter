"""Safe runtime identity logging for the Phase 2 SQLite connection."""
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


def _database_rows(connection):
    # This PRAGMA is deliberately executed through the caller's live SQLAlchemy
    # Connection, never through a second engine or diagnostic connection.
    return connection.exec_driver_sql("PRAGMA database_list").fetchall()


def log_runtime_database_identity(
    connection, *, event_name, service_name, config_source, opened_at=None,
):
    """Log identity from the exact SQLite connection used by the worker."""
    rows = _database_rows(connection)
    for row in rows:
        database_name = str(row[1] or "main")
        database_path = str(row[2] or "")
        if database_path:
            basename = PurePosixPath(database_path).name or "database"
            masked_path = ".../" + basename
            identity_material = database_name + "\\0" + database_path
        else:
            masked_path = "<memory-or-empty>"
            identity_material = database_name + "\\0<memory-or-empty>"
        fingerprint = hashlib.sha256(identity_material.encode("utf-8")).hexdigest()[:16]
        print(
            "PHASE2_RUNTIME_DATABASE "
            f"event={event_name} pid={os.getpid()} service={service_name} "
            f"config_source={config_source} database_name={database_name} "
            f"database_path={masked_path} database_id=sha256:{fingerprint} "
            f"connection_opened_at={opened_at or opened_at_utc()}",
            flush=True,
        )
