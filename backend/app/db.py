"""Database engine for the isolated Phase 2 canonical catalog.

SQLite remains the default until the separately approved PostgreSQL cutover.
The legacy retailer catalog is managed independently and must not use this
engine or its database URL.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

# Production continues on the isolated SQLite catalog until cutover approval.
DEFAULT_DATABASE_URL = "sqlite:////data/catalog/catalog.sqlite3"
_ENV_KEYS = ("SCENTHUNTER_CATALOG_DATABASE_URL", "SCENTHUNTER_DATABASE_URL")


def database_url(environ=None) -> str:
    """Return a validated SQLAlchemy URL without logging or exposing it."""
    env = os.environ if environ is None else environ
    value = next((env.get(key) for key in _ENV_KEYS if env.get(key)), DEFAULT_DATABASE_URL).strip()
    try:
        url = make_url(value)
    except Exception:
        raise RuntimeError("Invalid Phase 2 database URL configuration.") from None

    backend = url.get_backend_name()
    if backend == "sqlite":
        if url.database and url.database != ":memory:":
            Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        return url.render_as_string(hide_password=False)

    if backend == "postgresql":
        if url.drivername in {"postgres", "postgresql"}:
            url = url.set(drivername="postgresql+psycopg")
        elif url.drivername != "postgresql+psycopg":
            raise RuntimeError("Unsupported PostgreSQL driver for Phase 2; use psycopg 3.")
        if not url.database:
            raise RuntimeError("PostgreSQL Phase 2 database name is missing.")
        return url.render_as_string(hide_password=False)

    raise RuntimeError("Unsupported Phase 2 database dialect; use SQLite or PostgreSQL.")


def make_engine() -> Engine:
    url = database_url()
    parsed = make_url(url)
    backend = parsed.get_backend_name()

    if backend == "sqlite":
        connect_args = {"timeout": 30}
        if parsed.database == ":memory:":
            connect_args = {"check_same_thread": False}
        engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)

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

    # Keep PostgreSQL connections bounded for the current single-machine setup.
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=2,
        pool_recycle=1800,
    )


def make_session_factory():
    return sessionmaker(bind=make_engine(), expire_on_commit=False)
