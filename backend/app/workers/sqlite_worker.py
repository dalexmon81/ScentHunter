"""Single-process SQLite queue worker for the free single-machine pilot."""
from __future__ import annotations

import logging
import os
import signal
import socket
import time
import traceback
from datetime import datetime, timezone

from sqlalchemy import select

from app.db import make_session_factory
from app.models import Offer, Store
from app.workers import tasks as _registered_tasks  # registers the validated Notino handlers
from app.workers.runtime import get_handler
from app.workers.queueing import enqueue_offer_refresh
from app.workers.sqlite_queue import (
    claim_next, enqueue_daily_once, ensure_schema, fail_or_retry, finish, recover_stale,
)

logging.basicConfig(level=os.environ.get("SCENTHUNTER_WORKER_LOG_LEVEL", "INFO"))
log = logging.getLogger("scenthunter.sqlite_worker")
_STOP = False


def _stop(_signum, _frame):
    global _STOP
    _STOP = True


def _schedule_daily_notino_discovery(session_factory) -> None:
    day = datetime.now(timezone.utc).date().isoformat()
    try:
        with session_factory() as session:
            store_id = session.scalar(
                select(Store.id).where(Store.slug == "notino-fr", Store.status == "active")
            )
        if store_id is None:
            log.warning("No active notino-fr canonical store; discovery will be retried")
            return
        job_id = enqueue_daily_once(
            "schedule:notino-fr:daily-discovery",
            "discover",
            {"store_id": str(store_id), "cursor": None, "limit": 100},
            day,
        )
        if job_id:
            log.info("Queued daily Notino discovery job=%s day=%s", job_id, day)
    except Exception:
        log.exception("Unable to schedule daily Notino discovery")



def _schedule_notino_offer_refresh(session_factory) -> None:
    """Queue refreshes for current Notino offers; active jobs are deduplicated."""
    try:
        with session_factory() as session:
            rows = session.execute(
                select(Offer.store_id, Offer.external_product_id).join(Store)
                .where(Store.slug == "notino-fr", Store.status == "active",
                       Offer.status == "active", Offer.external_product_id.is_not(None))
                .order_by(Offer.captured_at.asc())
                .limit(500)
            ).all()
        queued = 0
        for store_id, external_product_id in rows:
            enqueue_offer_refresh(store_id, external_product_id)
            queued += 1
        if queued:
            log.info("Queued Notino offer refresh candidates=%s", queued)
    except Exception:
        log.exception("Unable to schedule Notino offer refresh")



def main() -> None:
    global _STOP
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    session_factory = make_session_factory()
    ensure_schema()
    log.info("SQLite ingestion worker started worker=%s queue_db=%s",
             worker_id, os.environ.get("SCENTHUNTER_SQLITE_QUEUE_DB", "/data/catalog/ingestion_queue.sqlite3"))
    last_recovery = 0.0
    last_schedule = 0.0
    last_refresh_schedule = 0.0
    while not _STOP:
        now = time.monotonic()
        if now - last_recovery >= 30:
            recovered = recover_stale()
            if recovered:
                log.warning("Recovered stale ingestion jobs count=%s", recovered)
            last_recovery = now
        if now - last_schedule >= 60:
            _schedule_daily_notino_discovery(session_factory)
            last_schedule = now
        if now - last_refresh_schedule >= 1800:
            _schedule_notino_offer_refresh(session_factory)
            last_refresh_schedule = now
        job = None
        try:
            job = claim_next(worker_id)
            if job is None:
                time.sleep(2)
                continue
            handler = get_handler(job["stage"])
            if handler is None:
                raise RuntimeError(f"no registered handler for stage={job['stage']}")
            log.info("Claimed ingestion job=%s stage=%s attempt=%s",
                     job["id"], job["stage"], job["attempts"])
            result = handler(job["payload"])
            finish(job["id"])
            log.info("Completed ingestion job=%s stage=%s result=%s",
                     job["id"], job["stage"], result)
        except Exception as exc:
            if job is not None:
                status = fail_or_retry(
                    job["id"], int(job["attempts"]),
                    f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
                )
                log.exception("Ingestion job=%s stage=%s status=%s",
                              job["id"], job["stage"], status)
            else:
                log.exception("SQLite ingestion worker loop error")
                time.sleep(5)
    session_factory.kw["bind"].dispose()
    log.info("SQLite ingestion worker stopped worker=%s", worker_id)


if __name__ == "__main__":
    main()
