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
    claim_next_smoke_job,
    generate_smoke_csv,
    finish_smoke_job,
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
            processed_stores=result.get("stores_processed", 0),
            finished_at=utc_now(),
            heartbeat_at=utc_now(),
            duration_seconds=elapsed,
        )
        print(
            f"PHASE0 WORKER JOB COMPLETED job={job['id']} "
            f"rows_written={result['rows_written']} "
            f"offers_read={result['offers_read']} store_statuses={result.get('store_statuses', {})} duration_seconds={elapsed} "
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



def _run_smoke_job(job: dict, worker_id: str) -> None:
    print(f"PHASE0 SMOKE WORKER CLAIMED job={job['id']} worker={worker_id}", flush=True)
    try:
        result = generate_smoke_csv(job)
        finish_smoke_job(
            job["id"], status="completed", finished_at=utc_now(),
            heartbeat_at=utc_now(), error_message=None,
        )
        print(
            f"PHASE0 SMOKE JOB COMPLETED job={job['id']} "
            f"rows_written={result['rows_written']} output={result['output_path']}",
            flush=True,
        )
    except Exception as exc:
        finish_smoke_job(
            job["id"], status="failed", finished_at=utc_now(),
            heartbeat_at=utc_now(), error_message=f"{type(exc).__name__}: {exc}",
        )
        print(f"PHASE0 SMOKE JOB FAILED job={job['id']} error={type(exc).__name__}: {exc}", flush=True)



def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    last_recovery = 0.0
    schema_ready = False
    pid_path = "/data/phase0/worker.pid"
    os.makedirs("/data/phase0", exist_ok=True)
    with open(pid_path, "w", encoding="ascii") as marker_file:
        marker_file.write(str(os.getpid()))
    print(f"PHASE0 WORKER START worker={worker_id} pid_file={pid_path}", flush=True)
    while not _STOP:
        try:
            # Re-open and initialize after transient SQLite/startup failures.
            # Queued rows remain durable on the mounted Fly volume.
            if not schema_ready:
                conn = connect()
                try:
                    ensure_schema(conn)
                finally:
                    conn.close()
                schema_ready = True

            if time.monotonic() - last_recovery >= 30:
                recovered = recover_stale_jobs()
                if recovered:
                    print(
                        f"PHASE0 WORKER STALE JOB RECOVERY worker={worker_id} "
                        f"jobs_failed={recovered}",
                        flush=True,
                    )
                last_recovery = time.monotonic()
            smoke_job = claim_next_smoke_job(worker_id)
            if smoke_job:
                _run_smoke_job(smoke_job, worker_id)
                continue
            job = claim_next_job(worker_id)
            if job:
                _run_job(job, worker_id)
            else:
                time.sleep(5)
        except Exception:
            schema_ready = False
            print(
                "PHASE0 WORKER LOOP ERROR\\n" + traceback.format_exc(),
                flush=True,
            )
            time.sleep(5)
    try:
        os.unlink(pid_path)
    except FileNotFoundError:
        pass
    print(f"PHASE0 WORKER STOP worker={worker_id}", flush=True)


if __name__ == "__main__":
    main()
