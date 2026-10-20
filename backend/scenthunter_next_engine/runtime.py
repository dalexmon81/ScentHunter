"""Safe opt-in integration helpers for the isolated next engine."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any


def next_engine_enabled(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get("SCENTHUNTER_NEXT_ENABLED", "0")).strip().lower() in {"1", "true", "yes", "on"}


def validated_database_path(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    configured = str(env.get("SCENTHUNTER_NEXT_DB", "")).strip()
    if not configured:
        raise RuntimeError("SCENTHUNTER_NEXT_DB must point to a separate next-engine database")
    target = Path(configured).expanduser().resolve()
    legacy = str(env.get("SCENTHUNTER_LEGACY_DB") or env.get("SCENTHUNTER_CATALOG_DB", "")).strip()
    if legacy and target == Path(legacy).expanduser().resolve():
        raise RuntimeError("next-engine database must not be the legacy catalog database")
    return target


def mount_next_engine(app: Any, *, environ: dict[str, str] | None = None) -> bool:
    """Mount /v2 only when explicitly enabled; return whether it was mounted.

    The caller must invoke this during application setup, before serving traffic.
    It never changes the legacy routes or the legacy database.
    """
    if not next_engine_enabled(environ):
        return False
    from .api import create_router
    path = validated_database_path(environ)
    app.include_router(create_router(path))
    return True
