"""Bootstrap the first Notino discovery on the canonical PostgreSQL queue.

This script is invoked directly on the dedicated Fly worker machine by the
deployment workflow. Keeping it as a file avoids nested-shell quoting issues.
"""
import json
import sys
import time

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

sys.path.insert(0, "/app/backend")

from app.db import make_engine
from app.models import Offer, Store
from app.workers.queueing import enqueue_discovery


def main() -> None:
    engine = make_engine()
    try:
        with Session(engine) as session, session.begin():
            store = session.scalar(select(Store).where(Store.slug == "notino-fr"))
            if store is None:
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
            elif store.status != "active":
                raise RuntimeError(
                    f"Notino store is not active (status={store.status!r}); "
                    "refusing automatic reactivation"
                )
            store_id = store.id

        task_id = enqueue_discovery(store_id, limit=1000)
        print(
            "NOTINO_DISCOVERY_ENQUEUED="
            + json.dumps(
                {"store_id": str(store_id), "task_id": str(task_id), "limit": 1000}
            ),
            flush=True,
        )

        deadline = time.monotonic() + 900
        last = {}
        while time.monotonic() < deadline:
            with engine.connect() as conn:
                counts = conn.execute(
                    text(
                        """
                        SELECT stage, status, count(*) AS n
                        FROM ingestion_queue_jobs
                        GROUP BY stage, status
                        """
                    )
                ).mappings().all()
                offer_count = conn.execute(
                    select(func.count()).select_from(Offer).where(
                        Offer.store_id == store_id
                    )
                ).scalar_one()
                completed_fetches = conn.execute(
                    text(
                        """
                        SELECT count(*) FROM ingestion_queue_jobs
                        WHERE stage='fetch' AND status='completed'
                        """
                    )
                ).scalar_one()
                failed_discovery = conn.execute(
                    text(
                        """
                        SELECT count(*) FROM ingestion_queue_jobs
                        WHERE stage='discover' AND status='failed'
                        """
                    )
                ).scalar_one()
                last_errors = conn.execute(
                    text(
                        """
                        SELECT stage, last_error FROM ingestion_queue_jobs
                        WHERE status='failed'
                        ORDER BY finished_at DESC NULLS LAST
                        LIMIT 3
                        """
                    )
                ).mappings().all()

            last = {
                "queue": [dict(row) for row in counts],
                "notino_offers": int(offer_count),
                "completed_fetches": int(completed_fetches),
                "failed_discovery": int(failed_discovery),
                "last_errors": [dict(row) for row in last_errors],
            }
            print(
                "NOTINO_INGESTION_PROGRESS="
                + json.dumps(last, default=str),
                flush=True,
            )
            if int(offer_count) > 0 and int(completed_fetches) > 0:
                print("NOTINO_POSTGRES_INGESTION=PASS", flush=True)
                return
            if int(failed_discovery) > 0 and int(completed_fetches) == 0:
                raise RuntimeError(
                    "Notino discovery failed before any fetch completed: "
                    + json.dumps(last, default=str)
                )
            time.sleep(10)

        raise TimeoutError(
            "No canonical Notino offer was persisted within 15 minutes: "
            + json.dumps(last, default=str)
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
