"""Bootstrap the first Notino discovery on the canonical PostgreSQL queue.

This script is invoked directly on the dedicated Fly worker machine by the
deployment workflow. Keeping it as a file avoids nested-shell quoting issues.
"""
import json
import sys
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

sys.path.insert(0, "/app/backend")

from app.db import make_engine
from app.models import Offer, Store
from app.workers.queueing import enqueue_discovery
from scripts.backfill_notino_verified_gtin import backfill_verified_notino_gtins


def _find_recent_discovery_job(conn, store_id, now: datetime):
    """Adopt the oldest recent Notino discovery page instead of restarting page one."""
    cutoff = now - timedelta(minutes=30)
    rows = conn.execute(
        text("""
            SELECT id, payload
            FROM ingestion_queue_jobs
            WHERE stage = 'discover'
              AND status IN ('queued', 'running', 'completed')
              AND created_at >= :cutoff
            ORDER BY created_at ASC, id ASC
        """),
        {"cutoff": cutoff},
    ).mappings().all()
    for row in rows:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(payload, dict) and str(payload.get("store_id")) == str(store_id):
            return row["id"]
    return None


def _discovery_batch_started_at(conn, task_id, bootstrap_started_at: datetime) -> datetime:
    """Reuse the creation time of a deduplicated in-flight discovery batch."""
    row = conn.execute(
        text("""
            SELECT created_at, status
            FROM ingestion_queue_jobs
            WHERE CAST(id AS text) = :job_id
        """),
        {"job_id": str(task_id)},
    ).mappings().one_or_none()
    if row is None:
        raise RuntimeError(f"Notino discovery queue job was not persisted: {task_id}")
    created_at = row["created_at"]
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    else:
        created_at = created_at.astimezone(timezone.utc)
    if (
        row["status"] in {"queued", "running"}
        and created_at < bootstrap_started_at - timedelta(minutes=30)
    ):
        raise RuntimeError(
            "An old Notino discovery job is still active; refusing to enqueue "
            "a duplicate batch."
        )
    return created_at


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

        bootstrap_started_at = datetime.now(timezone.utc)
        with engine.connect() as conn:
            task_id = _find_recent_discovery_job(
                conn, store_id, bootstrap_started_at
            )
        adopted_existing_batch = task_id is not None
        if task_id is None:
            task_id = enqueue_discovery(store_id, limit=1000)
        with engine.begin() as conn:
            batch_started_at = _discovery_batch_started_at(
                conn, task_id, bootstrap_started_at
            )
            priority_at = batch_started_at - timedelta(hours=24)
            conn.execute(
                text("""
                    UPDATE ingestion_queue_jobs
                    SET available_at = :priority_at
                    WHERE CAST(id AS text) = :job_id AND status = 'queued'
                """),
                {"priority_at": priority_at, "job_id": str(task_id)},
            )
        print(
            "NOTINO_DISCOVERY_ENQUEUED="
            + json.dumps(
                {"store_id": str(store_id), "task_id": str(task_id), "limit": 1000, "batch_started_at": batch_started_at.isoformat(), "adopted_existing_batch": adopted_existing_batch}
            ),
            flush=True,
        )

        deadline = time.monotonic() + 900
        last = {}
        while time.monotonic() < deadline:
            with engine.begin() as conn:
                # Prioritize only this bootstrap's Notino jobs ahead of the
                # migrated legacy backlog. No existing jobs are deleted or
                # rewritten; only jobs belonging to this Notino discovery
                # batch get an earlier availability timestamp.
                conn.execute(
                    text("""
                        UPDATE ingestion_queue_jobs
                        SET available_at = :priority_at
                        WHERE status = 'queued'
                          AND stage IN ('discover', 'fetch')
                          AND payload->>'store_id' = :store_id
                          AND created_at >= :started_at
                    """),
                    {
                        "priority_at": priority_at,
                        "store_id": str(store_id),
                        "started_at": batch_started_at,
                    },
                )
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
                        Offer.store_id == store_id,
                        Offer.captured_at >= batch_started_at,
                    )
                ).scalar_one()
                completed_fetches = conn.execute(
                    text(
                        """
                        SELECT count(*) FROM ingestion_queue_jobs
                        WHERE stage='fetch' AND status='completed'
                          AND payload->>'store_id' = :store_id
                          AND created_at >= :started_at
                        """
                    ), {"store_id": str(store_id), "started_at": batch_started_at}
                ).scalar_one()
                failed_discovery = conn.execute(
                    text(
                        """
                        SELECT count(*) FROM ingestion_queue_jobs
                        WHERE stage='discover' AND status='failed'
                          AND payload->>'store_id' = :store_id
                          AND created_at >= :started_at
                        """
                    ), {"store_id": str(store_id), "started_at": batch_started_at}
                ).scalar_one()
                last_errors = conn.execute(
                    text(
                        """
                        SELECT stage, last_error FROM ingestion_queue_jobs
                        WHERE status='failed'
                          AND payload->>'store_id' = :store_id
                          AND created_at >= :started_at
                        ORDER BY finished_at DESC NULLS LAST
                        LIMIT 3
                        """
                    ), {"store_id": str(store_id), "started_at": batch_started_at}
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
                with Session(engine) as session:
                    store = session.scalar(select(Store).where(Store.id == store_id))
                    if store is None:
                        raise RuntimeError("Notino store disappeared during GTIN backfill")
                    gtin_backfill = backfill_verified_notino_gtins(
                        session, store,
                        catalog_path="/app/backend/product_catalog.json",
                        apply=True,
                    )
                    session.commit()
                covered_gtins = (
                    int(gtin_backfill.get("promoted_unique_gtins", 0))
                    + int(gtin_backfill.get("skipped_reasons", {}).get(
                        "already_active_in_stock_offer", 0
                    ))
                )
                if covered_gtins != 4:
                    raise RuntimeError(
                        "Notino verified Dior Sauvage EDP GTIN backfill did not cover "
                        f"all four sizes: {json.dumps(gtin_backfill, default=str)}"
                    )
                print(
                    "NOTINO_VERIFIED_GTIN_BACKFILL="
                    + json.dumps(gtin_backfill, ensure_ascii=False, sort_keys=True),
                    flush=True,
                )
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
