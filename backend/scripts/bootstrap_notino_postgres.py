"""Bootstrap the canonical Notino PostgreSQL pilot using four reviewed Dior GTINs.

This is intentionally a targeted ingestion, not a full feed pagination job.
The authorized CJ/VIV snapshot is loaded once and only the four reviewed
Dior Sauvage EDP product IDs are eligible for promotion.
"""
import asyncio
import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import make_engine
from app.models import Offer, Store
from app.connectors.notino_feed import NotinoAffiliateFeedConnector
from scripts.backfill_notino_verified_gtin import (
    VERIFIED_GTINS,
    _fetch_current_feed_records,
    backfill_verified_notino_gtins,
)


def main() -> None:
    # Download the current authorized CJ/VIV snapshot before opening a DB session.
    # Neon enforces idle-in-transaction timeouts; network I/O must not run inside one.
    feed_records = asyncio.run(_fetch_current_feed_records(NotinoAffiliateFeedConnector()))
    engine = make_engine()
    try:
        with Session(engine) as session:
            store = session.scalar(select(Store).where(Store.slug == "notino-fr"))
            if store is None or store.status != "active":
                raise RuntimeError("Notino store is not active; refusing automatic reactivation")

            # The earlier failed bootstrap stamped two offers from old staged
            # feed rows as newly captured. Hide only those four reviewed EDP IDs
            # until this run refreshes them from the current authorized feed.
            session.execute(
                update(Offer)
                .where(
                    Offer.store_id == store.id,
                    Offer.external_product_id.in_([
                        item["external_product_id"] for item in VERIFIED_GTINS.values()
                    ]),
                )
                .values(valid_until=datetime.now(timezone.utc))
            )
            session.commit()

            summary = backfill_verified_notino_gtins(
                session,
                store,
                catalog_path="/app/backend/product_catalog.json",
                apply=True,
                feed_records=feed_records,
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
