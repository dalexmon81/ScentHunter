"""Bootstrap the isolated catalog pilot before API and worker startup.

This is intentionally safe to run on every single-machine pilot restart:
- Alembic upgrades the mounted catalog database to the current schema.
- Canonical identities are imported idempotently from the checked-in seed.
- Notino is created only when absent; existing inactive/quarantined states are
  never reactivated or overwritten.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.db import make_engine
from app.models import Store


def ensure_notino_store(session: Session) -> str:
    """Create the pilot store only when missing; preserve operator status."""
    store = session.scalar(select(Store).where(Store.slug == "notino-fr"))
    if store is not None:
        return f"preserved_existing_{store.status}"

    session.add(Store(
        name="Notino.fr",
        slug="notino-fr",
        domain="notino.fr",
        country="FR",
        currency="EUR",
        status="active",
    ))
    session.flush()
    return "created_active"


def main() -> int:
    python = sys.executable
    print("CATALOG_BOOTSTRAP step=migrations status=starting", flush=True)
    subprocess.run([python, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True)

    print("CATALOG_BOOTSTRAP step=canonical_seed status=starting", flush=True)
    subprocess.run(
        [python, str(BACKEND / "scripts" / "seed_catalog.py"), "--apply"],
        cwd=BACKEND,
        check=True,
    )

    engine = make_engine()
    try:
        with Session(engine) as session, session.begin():
            result = ensure_notino_store(session)
        print(f"CATALOG_BOOTSTRAP step=notino_store result={result}", flush=True)
    finally:
        engine.dispose()

    print("CATALOG_BOOTSTRAP status=ready", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
