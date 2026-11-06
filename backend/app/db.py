"""Database engine for the isolated canonical catalog (SQLite or PostgreSQL)."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

DEFAULT_DATABASE_URL = "sqlite:////data/catalog/catalog.sqlite3"


def database_url() -> str:
    value = (
        os.environ.get("SCENTHUNTER_CATALOG_DATABASE_URL")
        or os.environ.get("SCENTHUNTER_DATABASE_URL")
        or DEFAULT_DATABASE_URL
    ).strip()
    url = make_url(value)
    backend = url.get_backend_name()
    if backend not in {"sqlite", "postgresql"}:
        raise RuntimeError(
            f"Unsupported catalog database backend: {backend}. "
            "Use SQLite or PostgreSQL."
        )
    if backend == "sqlite" and url.database and url.database != ":memory:":
        Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    return value


def make_engine() -> Engine:
    url = database_url()
    parsed = make_url(url)
    connect_args = {"timeout": 30} if parsed.get_backend_name() == "sqlite" and parsed.database != ":memory:" else {}
    engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)

    if parsed.get_backend_name() == "sqlite":
        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            if parsed.database != ":memory:":
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    return engine


def make_session_factory():
    return sessionmaker(bind=make_engine(), expire_on_commit=False)
