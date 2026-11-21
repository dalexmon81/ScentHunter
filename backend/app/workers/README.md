# Workers layer

The catalog-first worker keeps retailer discovery, product fetch and offer
refresh outside HTTP request handlers. The implemented runtime currently has
three queue stages: `discover`, `fetch` and `refresh`.

## Runtime boundary

Notino, Bplatz and the four legacy retailer adapters (Deloox, Sabina,
Easycosmetic and Parfum-Zentrum) register handlers for discovery, fetch and
refresh.

A product fetch currently runs parsing, normalization, canonical matching,
validation and offer promotion together through
`app.services.connector_ingestion.persist_connector_record`. This is
intentional: the raw evidence, match result and published offer are written in
one caller-owned database transaction. Unmatched or invalid records remain
staged and are not published.

Normalization, matching, validation, quarantine and reprocess are not separate
queue consumers today. They are not advertised as runnable Celery tasks. A
future split must first define durable stage inputs/outputs, explicit status
transitions, idempotent retries and recovery behavior; merely adding queue
names would create jobs that fail at runtime or leave partially processed
records.

Connector quarantine is currently a direct health-service action from the
discovery/fetch/refresh handlers, not a dead-letter queue consumer. Five
consecutive connector-wide feed failures quarantine the store. Successful feed
access resets the streak only while the store remains active. Re-enabling a
quarantined store is an explicit operator action.

## Queue and deployment gates

The isolated single-machine pilot uses a durable SQLite queue on its existing
Fly volume. Redis/Celery is the optional multi-machine backend. The Celery
configuration exposes only the three implemented queues and uses persistent
delivery, late acknowledgements, worker-loss rejection, prefetch=1 and bounded
exponential retry with jitter.

Before enabling a separate Redis/Celery worker:

1. Move the pilot catalog from its machine-local SQLite volume to shared
   PostgreSQL. A separate Fly machine cannot share the app machine's SQLite
   volume; do not start a second worker against a separate local database.
2. Provision a dedicated Redis instance and set `SCENTHUNTER_REDIS_URL` only
   on the pilot app and worker.
3. Add a separate worker process/deployment; do not run ingestion inside
   FastAPI.
4. Verify idempotency and recovery against a disposable PostgreSQL database
   and a real Redis broker.
5. Complete backup/restore and canary/rollback checks before any production
   activation.

No Redis connection is attempted at import time. Queue submission fails closed
when no explicit Redis URL exists. A successful CI worker smoke test proves
broker-to-worker execution in CI only; it does not prove a Fly worker is
deployed or connected to a shared database.

Run focused tests from `backend` with:

```bash
python -m unittest discover -s tests -p 'test_catalog_worker_queue.py' -v
```

## Durable ingestion run tracking

`app.workers.ingestion_run` provides transaction-scoped helpers for creating,
updating and closing `IngestionRun` rows. A worker records progress in small
transactions, retains bounded error messages and closes each run as
`completed`, `partial` or `failed`. The helpers never commit on behalf of
the caller.

## Notino pilot

The Notino connector reads the authorized CJ/VIV feed snapshot. Discovery
queues one fetch task per retailer product. Fetch stages the original evidence,
uses the database-native canonical matcher first, and retains the legacy
catalog matcher only as a conservative fallback through explicit persisted ID
maps. Publication requires a resolved canonical UUID, explicit currency
provenance, valid positive price, valid URL and explicit stock. Unmatched or
ambiguous products remain in staging.

The pilot catalog must explicitly seed the `notino-fr` store before discovery.
To add only the missing store row (without re-importing canonical identities):

```bash
cd backend
python scripts/seed_notino_store.py --confirm
```

The command is idempotent, refuses to reactivate an inactive or quarantined row,
and does not contact the CJ feed. The broader catalog seed remains available
as `seed_catalog.py --apply --seed-notino-store`.

After shared PostgreSQL, Redis and a separate worker are ready, the first
Notino run is an explicit operator action:

```bash
cd backend
python scripts/enqueue_notino_discovery.py --limit 100
```

The command only enqueues discovery. It fails closed if Redis is not configured
or the active `notino-fr` store has not been seeded.

## Offer refresh

The isolated SQLite pilot registers the Notino refresh handler. Every 30 minutes
the single-machine worker queues up to 200 oldest active offers per enabled
retailer with a stable external product ID. Active duplicate jobs are coalesced
by the durable queue. Refresh reads the latest authorized feed snapshot,
requires explicit price, currency provenance, URL and stock, and updates the
existing offer without changing its canonical variant. A successful
observation is retained in `price_history` and raw refresh evidence is staged
in `ingestion_raw`.

This schedule is limited to the pilot. It does not claim a 15-minute freshness
guarantee or establish that all retailer refreshes are active in production.

## Bplatz adapter\n\nBplatz has isolated discovery, fetch and refresh handlers in\n`app.workers.bplatz_runtime`. The generic dispatcher routes only the canonical\n`bplatz` store slug to these handlers. The handlers require an already seeded,\nactive Bplatz store and use the shared staging/matching/promotion and refresh\nservices. They do not seed the store, enable scheduling, or start network work\nat process startup. Bplatz discovery and refresh jobs must be explicitly\nenqueued; the default scheduler does not include Bplatz.\n\n## Legacy retailer adapters

Deloox, Sabina, Easycosmetic and Parfum-Zentrum have thin async adapters around
their existing scraper modules. The existing retailer parsers remain the
authority for page extraction; the adapters normalize their output, retain raw
evidence, require explicit JSON-LD currency provenance and pass records through
the same canonical matching and publication service as Notino.

The stores are not silently activated. Seed only retailer rows that have been
reviewed and approved:

```bash
cd backend
python scripts/seed_catalog.py --apply --seed-deloox-store
python scripts/seed_catalog.py --apply --seed-sabina-store
python scripts/seed_catalog.py --apply --seed-easycosmetic-store
python scripts/seed_catalog.py --apply --seed-parfumzentrum-store
```

Each command is opt-in and creates/activates only the named store row. Before
discovery can be scheduled, configure semicolon-separated operator-approved
seed queries for each retailer, for example:

```bash
SCENTHUNTER_DISCOVERY_QUERIES_DELOOX="Dior Sauvage;Chanel No 5"
SCENTHUNTER_DISCOVERY_QUERIES_SABINA="Dior Sauvage;Chanel No 5"
SCENTHUNTER_DISCOVERY_QUERIES_EASYCOSMETIC="Dior Sauvage;Chanel No 5"
SCENTHUNTER_DISCOVERY_QUERIES_PARFUMZENTRUM="Dior Sauvage;Chanel No 5"
```

The single-machine worker schedules daily discovery only for explicitly seeded
stores that also have query seeds configured. User-facing catalog search does
not call these scrapers. Offers without unambiguous canonical matches, explicit
stock, valid price/URL or source-backed currency remain in staging and are not
published. Refresh re-fetches the known product URL and never rematches or
changes the canonical variant.

The isolated pilot deployment is separate from production. Production
deployment requires separate explicit approval.
