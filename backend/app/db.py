"""PostgreSQL-only database engine for the canonical ScentHunter catalog."""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

_ENV_KEYS = ("SCENTHUNTER_CATALOG_DATABASE_URL", "SCENTHUNTER_DATABASE_URL")


def database_url(environ=None) -> str:
    """Return a validated PostgreSQL URL; there is deliberately no local DB fallback."""
    env = os.environ if environ is None else environ
    value = next((env.get(key) for key in _ENV_KEYS if env.get(key)), None)
    if not value or not value.strip():
        raise RuntimeError(
            "PostgreSQL catalog is mandatory. Configure SCENTHUNTER_CATALOG_DATABASE_URL."
        )
    try:
        url = make_url(value.strip())
    except Exception:
        raise RuntimeError("Invalid PostgreSQL catalog URL configuration.") from None
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    if url.get_backend_name() != "postgresql" or url.drivername != "postgresql+psycopg":
        raise RuntimeError("ScentHunter supports PostgreSQL only; configure psycopg 3.")
    if not url.database:
        raise RuntimeError("PostgreSQL catalog database name is missing.")
    return url.render_as_string(hide_password=False)


def make_engine() -> Engine:
    return create_engine(
        database_url(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=2,
        pool_recycle=1800,
    )


def make_session_factory():
    return sessionmaker(bind=make_engine(), expire_on_commit=False)
