# Workers layer

Background ingestion, discovery, offer refresh, validation, matching, retry, and quarantine jobs. Keep long-running store work out of HTTP request handlers.

## Phase 5 queue foundation

The catalog-first branch defines a Celery application using Redis as broker.
Queues are separated by responsibility: discovery, offers, normalization,
matching, validation, refresh and dead_letter. Producer helpers send JSON-only
identifiers and payloads. Celery uses persistent delivery, late acknowledgements,
worker-loss rejection, prefetch=1 and bounded exponential retry with jitter.

## Activation gates

This is queue infrastructure, not a claim that a live worker is already running.
Before enabling it in the isolated pilot:

1. Provision a dedicated Redis instance and set SCENTHUNTER_REDIS_URL only on
   the pilot app and worker.
2. Add a separate worker process/deployment; do not run ingestion inside FastAPI.
3. Register stage handlers using the canonical DB session factory, connector
   registry and persist_connector_record.
4. Persist ingestion-run counters, connector failure streaks and quarantine
   state before enabling recurring schedules.
5. Verify idempotency and recovery using a disposable DB and a real Redis broker.

No Redis connection is attempted at import time. Queue submission fails closed
when no explicit Redis URL exists. The production app and legacy refresh worker
remain unchanged.

Run focused tests from backend with:
python -m unittest discover -s tests -p 'test_catalog_worker_queue.py' -v


## Durable ingestion run tracking

`app.workers.ingestion_run` provides transaction-scoped helpers for creating,
updating, and closing `IngestionRun` rows. A worker should record progress in
small transactions, retain bounded error messages, and close each run as
`completed`, `partial`, or `failed`. The helpers never commit on behalf of
the caller.

This is persistence infrastructure only. It does not register retailer handlers,
start Celery workers, provision Redis, or activate ingestion.
