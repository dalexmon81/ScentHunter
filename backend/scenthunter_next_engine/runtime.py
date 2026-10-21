"""Safe opt-in integration helpers for the isolated ScentHunter next engine.

Architecture boundary:
- the legacy catalog remains the production read/write system until an
  independently validated migration is explicitly published;
- the next engine owns a different SQLite file and never aliases the legacy DB;
- failure to initialize the optional next engine must not prevent the legacy
  FastAPI application from starting;
- a failed mount is reported clearly and does not silently enable fallback
  matching or mutate either database.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def next_engine_enabled(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get("SCENTHUNTER_NEXT_ENABLED", "0")).strip().lower() in {
        "1", "true", "yes", "on"
    }


def validated_database_path(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    configured = str(env.get("SCENTHUNTER_NEXT_DB", "")).strip()
    if not configured:
        raise RuntimeError(
            "SCENTHUNTER_NEXT_DB must point to a separate next-engine database"
        )

    target = Path(configured).expanduser().resolve()
    legacy = str(
        env.get("SCENTHUNTER_LEGACY_DB")
        or env.get("SCENTHUNTER_CATALOG_DB", "")
    ).strip()
    if legacy and target == Path(legacy).expanduser().resolve():
        raise RuntimeError(
            "next-engine database must not be the legacy catalog database"
        )
    return target


def mount_next_engine(
    app: Any,
    *,
    environ: dict[str, str] | None = None,
) -> bool:
    """Mount /v2 only when enabled; keep legacy startup independent of /v2.

    Returns True only when the router was successfully initialized and mounted.
    Initialization errors are logged and converted to False so an optional
    next-engine database/storage failure cannot take down the legacy service.
    No migration is started here and no legacy data is changed.
    """
    if not next_engine_enabled(environ):
        return False

    try:
        path = validated_database_path(environ)
        from .api import create_router

        router = create_router(path)
        app.include_router(router)
    except Exception as exc:
        # Do not mask the problem: keep the exact error in platform logs.
        # Do not re-raise: /v2 is optional until the migration is verified.
        print(
            "NEXT_ENGINE_MOUNT_FAILED: "
            f"{type(exc).__name__}: {exc}. Legacy application remains active; "
            "next engine was not mounted.",
            flush=True,
        )
        return False

    print(f"NEXT_ENGINE_MOUNTED: database={path}", flush=True)
    return True
