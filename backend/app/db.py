"""Database engine for the canonical catalog.

PostgreSQL is mandatory in the production runtime. SQLite is available only
when a caller explicitly supplies a SQLite URL (tests/local isolated tools);
there is no implicit local-database fallback.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

_ENV_KEYS = ("SCENTHUNTER_CATALOG_DATABASE_URL", "SCENTHUNTER_DATABASE_URL")
_REQUIRE_POSTGRESQL_ENV = "SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off", ""}


def _postgresql_required(env) -> bool:
    raw = env.get(_REQUIRE_POSTGRESQL_ENV)
    if raw is None:
        return False
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise RuntimeError(f"Invalid {_REQUIRE_POSTGRESQL_ENV} value: expected a boolean.")


def database_url(environ=None) -> str:
    """Return a validated explicitly configured database URL."""
    env = os.environ if environ is None else environ
    value = next((env.get(key) for key in _ENV_KEYS if env.get(key)), None)
    if not value or not value.strip():
        raise RuntimeError(
            "PostgreSQL catalog is mandatory. Configure SCENTHUNTER_CATALOG_DATABASE_URL."
        )
    try:
        url = make_url(value.strip())
    except Exception:
        raise RuntimeError("Invalid catalog database URL configuration.") from None

    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")

    backend = url.get_backend_name()
    if backend == "postgresql":
        if url.drivername != "postgresql+psycopg":
            raise RuntimeError("Unsupported PostgreSQL driver; use psycopg 3.")
        if not url.database:
            raise RuntimeError("PostgreSQL catalog database name is missing.")
    elif backend == "sqlite":
        if _postgresql_required(env):
            raise RuntimeError(
                f"{_REQUIRE_POSTGRESQL_ENV}=1 requires PostgreSQL; SQLite is restricted to isolated tests/local tools."
            )
    else:
        raise RuntimeError("Unsupported catalog database dialect; use PostgreSQL.")

    return url.render_as_string(hide_password=False)


def make_engine() -> Engine:
    url = database_url()
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        if parsed.database and parsed.database != ":memory:":
            Path(parsed.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
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

    return create_engine(
        url, pool_pre_ping=True, pool_size=5, max_overflow=2, pool_recycle=1800
    )


def make_session_factory():
    return sessionmaker(bind=make_engine(), expire_on_commit=False)
