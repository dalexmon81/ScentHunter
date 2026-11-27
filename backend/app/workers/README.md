# Workers layer

The catalog-first worker keeps retailer discovery, product fetch and offer
refresh outside HTTP request handlers. The implemented runtime currently has
three queue stages: `discover`, `fetch` and `refresh`.

## Runtime boundary

Notino and the five retailer adapters (Bplatz, Deloox, Sabina, Easycosmetic and
Parfum-Zentrum) register handlers for discovery, fetch and refresh.

A product fetch first uses `app.extraction.product.extract_product_record` to
fetch and preserve the raw source mapping. Parsing, normalization, canonical
matching, validation and offer promotion then run through
`app.offers.ingestion.persist_connector_record`. This is intentional: the raw evidence, match result and published offer are written in
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

The production Fly deployment runs the dedicated PostgreSQL worker process
from `app.workers.postgres_worker`. `fly.toml` explicitly sets
`SCENTHUNTER_QUEUE_BACKEND=postgres`; jobs are persisted in
`ingestion_queue_jobs`, claimed with PostgreSQL locking, retried with bounded
backoff and recovered when a worker lease becomes stale.

The production worker schedules daily discovery for the active Notino.fr store
and for other explicitly seeded retailers with configured query seeds. It also
schedules active-offer refresh every 30 minutes. Discovery, fetch and refresh
are the only implemented queue stages. Normalization, canonical matching,
validation and publication remain inside the fetch transaction; they are not
separate queue consumers today.

SQLite and Redis/Celery remain available as alternate backends for isolated
tests or pilots. They are not the production Fly queue. Do not start another
worker with a local SQLite queue against the production PostgreSQL catalog.
Redis/Celery requires an explicitly configured broker and a separately
deployed worker; adding queue names alone does not create working consumers.

Before changing the production queue backend or adding another worker:

1. Define durable stage inputs/outputs, idempotent retries and recovery.
2. Verify queue behavior against a disposable PostgreSQL database.
3. Complete backup/restore and canary/rollback checks.
4. Confirm that only one intended production worker is claiming each queue.

No Redis connection is attempted at import time. Queue submission fails closed
when Redis is selected but no explicit Redis URL exists. CI worker smoke tests
do not prove a Fly worker is deployed or connected to production.

Run focused tests from `backend` with:

```bash
python -m unittest discover -s tests -p 'test_catalog_worker_queue.py' -v
```

## Durable ingestion run tracking

`app.repositories.ingestion_runs` provides transaction-scoped helpers for creating,
updating and closing `IngestionRun` rows. A worker records progress in small
transactions, retains bounded error messages and closes each run as
`completed`, `partial` or `failed`. The helpers never commit on behalf of
the caller.

## Notino direct storefront connector

Production Notino discovery, fetch and refresh use
`app.connectors.notino_public.NotinoPublicStorefrontConnector`. The PostgreSQL
worker runtime does not import or instantiate the CJ/VIV feed connector.

Discovery runs bounded public Notino.fr searches using
`SCENTHUNTER_DISCOVERY_QUERIES_NOTINO`. If that setting is empty, the connector
uses a small five-query pilot seed. Search candidates are deduplicated by their
Notino product URL and known face-care/non-perfume result markers are rejected.
A candidate's brand can be recovered from the first URL path segment only when
the product title repeats that same brand prefix.

Fetch and refresh read the exact HTTPS Notino.fr product page through the
existing Notino parser using direct storefront requests only. If the retailer
blocks the request, the connector fails closed; it does not use a proxy, public
reader, feed or alternate access path. The parser uses the product's stock/price-per-ml line or matching Product JSON-LD for price,
size and stock; it does not use delivery charges or search-card prices. The
connector preserves the product URL and extracts the product name, brand,
concentration, size, price, explicit EUR evidence and explicit stock state.
It never downloads or parses the CJ/VIV feed.

Publication requires a database-native canonical variant match, explicit EUR
evidence, positive price, valid product URL, explicit stock state and a current
capture timestamp. Notino does not use the legacy JSON catalog matcher as a
fallback. Unknown or ambiguous identities remain pending for review. Public
search accepts the direct connector's own `captured_at` timestamp, but does
not use download time as freshness evidence for legacy CJ/VIV records.

The live connector smoke test is read-only and must not touch PostgreSQL:

```bash
cd backend
PYTHONPATH=. python scripts/notino_direct_connector_smoke.py
```

The production scheduled CJ/VIV feed writer has been retired. The old feed
parser and its tests remain isolated as legacy compatibility code; the
historical feed monitor is manual-only and is not part of production ingestion.

The Notino store must still be explicitly provisioned before discovery. To add
only the missing store row (without re-importing canonical identities):

```bash
cd backend
python scripts/seed_notino_store.py --confirm
```

The command is idempotent, refuses to reactivate an inactive or quarantined row,
and does not contact any retailer. The broader catalog seed remains available
as `seed_catalog.py --apply --seed-notino-store`.

## Offer refresh

The PostgreSQL worker schedules active-offer refresh every 30 minutes when
`SCENTHUNTER_ACTIVE_OFFER_REFRESH_ENABLED=1`. Notino refresh uses the stored
canonical product URL, including for legacy offers whose external IDs were CJ
identifiers. It re-fetches the public product page, requires explicit price,
EUR currency evidence, URL and stock, and updates the existing offer without
changing its canonical variant. A successful observation is retained in
`price_history` and raw refresh evidence is staged in `ingestion_raw`.

The 30-minute scheduling interval is a queueing cadence, not a freshness
guarantee. Public search independently enforces the 24-hour publication window
and the stricter Notino source-observation checks.

## Legacy retailer adapters

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
