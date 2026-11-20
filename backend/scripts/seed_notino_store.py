"""Explicitly provision the Notino.fr store row without re-importing the catalog.

This command only creates the missing store row. It never reactivates an
existing inactive or quarantined connector and never downloads the CJ feed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.db import make_engine
from app.models import Store


def ensure_notino_store(session: Session) -> dict:
    store = session.scalar(select(Store).where(Store.slug == "notino-fr"))
    if store is not None:
        if store.status != "active":
            raise RuntimeError(
                f"Notino store exists with status={store.status!r}; refusing automatic reactivation."
            )
        return {"status": "already_active", "store_id": str(store.id), "slug": store.slug}

    store = Store(
        name="Notino.fr",
        slug="notino-fr",
        domain="notino.fr",
        country="FR",
        currency="EUR",
        status="active",
    )
    session.add(store)
    session.flush()
    return {"status": "created", "store_id": str(store.id), "slug": store.slug}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm", action="store_true",
        help="confirm creation of the missing active Notino.fr store row",
    )
    args = parser.parse_args()
    if not args.confirm:
        parser.error("refusing to write without --confirm")

    engine = make_engine()
    try:
        with Session(engine) as session, session.begin():
            result = ensure_notino_store(session)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
