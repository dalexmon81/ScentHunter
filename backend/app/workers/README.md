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

1. Move the pilot catalog from its machine-local SQLite volume to shared
   PostgreSQL. A separate Fly machine cannot share the app machine's SQLite
   volume; do not start a second worker against a separate local DB.
2. Provision a dedicated Redis instance and set SCENTHUNTER_REDIS_URL only on
   the pilot app and worker.
3. Add a separate worker process/deployment; do not run ingestion inside FastAPI.
4. Register stage handlers using the canonical DB session factory, connector
   registry and persist_connector_record. The Notino discovery and fetch
   handlers are now wired; other retailers remain unregistered.
5. Persist connector failure streaks and quarantine state before enabling
   recurring schedules.
6. Verify idempotency and recovery using a disposable PostgreSQL DB and a real
   Redis broker.

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


## Notino pilot runtime

The worker bootstrap registers Notino's discovery and fetch handlers. Discovery
reads one page from the authorized CJ/VIV feed snapshot and queues one fetch task
per retailer product. Fetch stages the original record, normalizes it, resolves
only existing legacy-to-canonical UUID mappings, validates explicit price,
currency, URL and stock, and promotes only safe matches. Each discovery page and
product fetch has a durable `IngestionRun` record. Unmatched products remain in
staging and are not published.

The pilot catalog must explicitly seed the `notino-fr` store with
`seed_catalog.py --apply --seed-notino-store`. A Redis broker, shared PostgreSQL catalog, and separate Celery worker are
still required before these handlers can execute.
