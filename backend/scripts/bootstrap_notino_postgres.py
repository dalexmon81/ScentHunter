"""Bootstrap the canonical Notino PostgreSQL pilot using four reviewed Dior GTINs.

This is intentionally a targeted ingestion, not a full feed pagination job.
The authorized CJ/VIV snapshot is loaded once and only the four reviewed
Dior Sauvage EDP product IDs are eligible for promotion.
"""
import json
import sys

sys.path.insert(0, "/app/backend")

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import make_engine
from app.models import Store
from scripts.backfill_notino_verified_gtin import (
    VERIFIED_GTINS,
    backfill_verified_notino_gtins,
)


def main() -> None:
    engine = make_engine()
    try:
        with Session(engine) as session:
            store = session.scalar(select(Store).where(Store.slug == "notino-fr"))
            if store is None or store.status != "active":
                raise RuntimeError("Notino store is not active; refusing automatic reactivation")

            summary = backfill_verified_notino_gtins(
                session,
                store,
                catalog_path="/app/backend/product_catalog.json",
                apply=True,
            )
            if int(summary.get("promoted_unique_gtins", 0)) != len(VERIFIED_GTINS):
                raise RuntimeError(
                    "Targeted Notino Dior Sauvage EDP pilot did not promote all four "
                    "reviewed GTINs: " + json.dumps(summary, ensure_ascii=False, sort_keys=True)
                )
            session.commit()
            print(
                "NOTINO_TARGETED_POSTGRES_INGESTION="
                + json.dumps(summary, ensure_ascii=False, sort_keys=True),
                flush=True,
            )
            print("NOTINO_POSTGRES_INGESTION=PASS", flush=True)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
