"""Dedicated PostgreSQL queue worker for canonical catalog ingestion."""
from __future__ import annotations

import logging
import os
import signal
import socket
import time
import traceback

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


def main() -> None:
    global _STOP
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    session_factory = make_session_factory()
    log.info("PostgreSQL ingestion worker started worker=%s", worker_id)
    last_recovery = 0.0
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
