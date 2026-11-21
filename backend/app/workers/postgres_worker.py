"""Dedicated PostgreSQL queue worker for canonical catalog ingestion."""
from __future__ import annotations

import logging
import os
import signal
import socket
import time
import traceback
from datetime import datetime, timezone

from sqlalchemy import select
from app.models import Offer, Store
from app.connectors.legacy_scrapers import STORE_SLUGS
from app.workers.queueing import enqueue_offer_refresh
from app.workers.postgres_queue import enqueue_daily_once

from app.db import make_session_factory
from app.workers import tasks as _registered_tasks  # noqa: F401
from app.workers.runtime import get_handler
from app.workers.postgres_queue import claim_next, fail_or_retry, finish, recover_stale

logging.basicConfig(level=os.environ.get("SCENTHUNTER_WORKER_LOG_LEVEL", "INFO"))
log = logging.getLogger("scenthunter.postgres_worker")
_STOP = False


def _stop(_signum, _frame):
    global _STOP
    _STOP = True


def _schedule_daily_discovery(session_factory) -> None:
    day = datetime.now(timezone.utc).date().isoformat()
    try:
        with session_factory() as session:
            store_id = session.scalar(select(Store.id).where(Store.slug == "notino-fr", Store.status == "active"))
        if store_id is not None:
            job_id = enqueue_daily_once("schedule:notino-fr:daily-discovery", "discover",
                {"store_id": str(store_id), "cursor": None, "limit": 100}, day)
            if job_id:
                log.info("Queued daily Notino discovery job=%s day=%s", job_id, day)
        with session_factory() as session:
            stores = session.execute(select(Store.id, Store.slug).where(
                Store.status == "active", Store.slug.in_(tuple(STORE_SLUGS))
            )).all()
        for store_id, slug in stores:
            connector_key = STORE_SLUGS[slug]
            if not os.environ.get("SCENTHUNTER_DISCOVERY_QUERIES_" + connector_key.upper(), "").strip():
                continue
            job_id = enqueue_daily_once("schedule:" + slug + ":daily-discovery", "discover",
                {"store_id": str(store_id), "cursor": None, "limit": 100}, day)
            if job_id:
                log.info("Queued daily legacy discovery store=%s job=%s", slug, job_id)
    except Exception:
        log.exception("Unable to schedule daily PostgreSQL discovery")


def _schedule_active_offer_refresh(session_factory) -> None:
    enabled = os.environ.get("SCENTHUNTER_ACTIVE_OFFER_REFRESH_ENABLED", "1").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return
    try:
        with session_factory() as session:
            rows = session.execute(select(Offer.store_id, Offer.external_product_id).join(Store).where(
                Store.status == "active", Store.slug.in_(("notino-fr", *tuple(STORE_SLUGS))),
                Offer.status == "active",
                Offer.external_product_id.is_not(None)
            ).order_by(Offer.captured_at.asc()).limit(200)).all()
        for store_id, external_product_id in rows:
            enqueue_offer_refresh(store_id, external_product_id)
    except Exception:
        log.exception("Unable to schedule PostgreSQL active-offer refresh")


def main() -> None:
    global _STOP
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    session_factory = make_session_factory()
    log.info("PostgreSQL ingestion worker started worker=%s", worker_id)
    last_recovery = 0.0
    last_schedule = 0.0
    last_refresh_schedule = 0.0
    while not _STOP:
        now = time.monotonic()
        if now - last_recovery >= 30:
            try:
                recovered = recover_stale()
                if recovered:
                    log.warning("Recovered stale PostgreSQL ingestion jobs count=%s", recovered)
            except Exception:
                log.exception("PostgreSQL queue stale-job recovery failed")
            last_recovery = now
        if now - last_schedule >= 60:
            _schedule_daily_discovery(session_factory)
            last_schedule = now
        if now - last_refresh_schedule >= 1800:
            _schedule_active_offer_refresh(session_factory)
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
            log.info("Claimed PostgreSQL job=%s stage=%s attempt=%s",
                     job["id"], job["stage"], job["attempts"])
            result = handler(job["payload"])
            finish(str(job["id"]))
            log.info("Completed PostgreSQL job=%s stage=%s result=%s",
                     job["id"], job["stage"], result)
        except Exception as exc:
            if job is not None:
                status = fail_or_retry(
                    str(job["id"]), int(job["attempts"]),
                    f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
                    retryable=not isinstance(exc, (ValueError, TypeError, LookupError)),
                )
                log.exception("PostgreSQL job=%s stage=%s status=%s",
                              job["id"], job["stage"], status)
            else:
                log.exception("PostgreSQL worker loop error")
                time.sleep(5)
    session_factory.kw["bind"].dispose()
    log.info("PostgreSQL ingestion worker stopped worker=%s", worker_id)


if __name__ == "__main__":
    main()
