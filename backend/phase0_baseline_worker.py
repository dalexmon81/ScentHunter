"""Separate persistent Phase 0 baseline worker process."""
from __future__ import annotations

import os
import signal
import socket
import time
import traceback

from scenthunter_next_engine.phase0_baseline_jobs import (
    claim_next_job,
    ensure_schema,
    connect,
    recover_stale_jobs,
    update_job,
    generate_csv,
    utc_now,
)

_STOP = False


def _stop(_signum, _frame):
    global _STOP
    _STOP = True


def _run_job(job: dict, worker_id: str) -> None:
    started = time.monotonic()
    print(
        f"PHASE0 WORKER CLAIMED job={job['id']} worker={worker_id} status=running",
        flush=True,
    )
    try:
        result = generate_csv(job, worker_id)
        elapsed = round(time.monotonic() - started, 3)
        update_job(
            job["id"],
            status="completed",
            progress=1.0,
            processed_stores=11,
            finished_at=utc_now(),
            heartbeat_at=utc_now(),
            duration_seconds=elapsed,
        )
        print(
            f"PHASE0 WORKER JOB COMPLETED job={job['id']} "
            f"rows_written={result['rows_written']} "
            f"offers_read={result['offers_read']} duration_seconds={elapsed} "
            f"output={result['output_path']}",
            flush=True,
        )
    except Exception as exc:
        trace = traceback.format_exc()
        elapsed = round(time.monotonic() - started, 3)
        try:
            update_job(
                job["id"],
                status="failed",
                finished_at=utc_now(),
                heartbeat_at=utc_now(),
                duration_seconds=elapsed,
                error_message=f"{type(exc).__name__}: {exc}",
                error_traceback=trace,
            )
        finally:
            print(
                f"PHASE0 WORKER JOB FAILED job={job['id']} "
                f"duration_seconds={elapsed} error={type(exc).__name__}: {exc}\n"
                f"{trace}",
                flush=True,
            )


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    last_recovery = 0.0
    print(f"PHASE0 WORKER START worker={worker_id}", flush=True)
    while not _STOP:
        try:
            # Re-open and initialize after transient SQLite/startup failures.
            # Queued rows remain durable on the mounted Fly volume.
            conn = connect()
            try:
                ensure_schema(conn)
            finally:
                conn.close()

            if time.monotonic() - last_recovery >= 30:
                recovered = recover_stale_jobs()
                if recovered:
                    print(
                        f"PHASE0 WORKER STALE JOB RECOVERY worker={worker_id} "
                        f"jobs_failed={recovered}",
                        flush=True,
                    )
                last_recovery = time.monotonic()
            job = claim_next_job(worker_id)
            if job:
                _run_job(job, worker_id)
            else:
                time.sleep(5)
        except Exception:
            print(
                "PHASE0 WORKER LOOP ERROR\\n" + traceback.format_exc(),
                flush=True,
            )
            time.sleep(5)
    print(f"PHASE0 WORKER STOP worker={worker_id}", flush=True)


if __name__ == "__main__":
    main()
