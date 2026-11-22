"""Provision the four catalog-first legacy retailer rows without touching offers.

Dry-run is the default. --apply creates only missing rows; existing inactive
or quarantined rows are never silently reactivated.
"""
from __future__ import annotations

import argparse
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import make_engine
from app.models import Store

RETAILERS = (
    {"name": "Deloox.be", "slug": "deloox-be", "domain": "www.deloox.be", "country": "BE", "currency": "EUR"},
    {"name": "Sabina", "slug": "sabina-es", "domain": "www.sabina.com", "country": "ES", "currency": "EUR"},
    {"name": "Easycosmetic.de", "slug": "easycosmetic-de", "domain": "www.easycosmetic.de", "country": "DE", "currency": "EUR"},
    {"name": "Parfum-Zentrum.de", "slug": "parfumzentrum-de", "domain": "www.parfum-zentrum.de", "country": "DE", "currency": "EUR"},
)


def provision(session: Session, *, apply: bool) -> dict:
    created = []
    already_active = []
    blocked = []
    for data in RETAILERS:
        row = session.scalar(select(Store).where(Store.slug == data["slug"]))
        if row is not None:
            if row.status != "active" or row.domain != data["domain"]:
                blocked.append({"slug": data["slug"], "status": row.status, "domain": row.domain})
            else:
                already_active.append(data["slug"])
            continue
        created.append(data["slug"])
        if apply:
            session.add(Store(**data, status="active"))
    if blocked:
        raise RuntimeError("Existing retailer rows need manual review; refusing to reactivate or overwrite: " + json.dumps(blocked))
    return {
        "status": "provisioned" if apply else "validated",
        "created": created,
        "already_active": already_active,
        "database_written": bool(apply and created),
        "offers_imported": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="create missing active retailer rows")
    args = parser.parse_args()
    engine = make_engine()
    try:
        with Session(engine) as session:
            if args.apply:
                with session.begin():
                    report = provision(session, apply=True)
            else:
                report = provision(session, apply=False)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
