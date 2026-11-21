# ScentHunter 2.0 — Offer-First execution blueprint

Status: implementation blueprint; no production migration authorized
Branch: architecture/offer-first-v2
Date: 2026-11-21

## 1. Product and runtime contract

ScentHunter must behave as a catalog-first price comparison service.

- A customer search reads the canonical catalog and already-ingested, validated offers.
- Customer search never starts a retailer scrape, downloads a feed, waits for a retailer, or writes to the catalog.
- Retailer acquisition runs independently in background jobs. It discovers retailer products, stages raw evidence, normalizes identity and price data, matches to canonical variants, validates, then promotes offers.
- Price and stock refreshes update existing offers independently of discovery.
- An offer that is unmatched, ambiguous, stale, invalid, or missing explicit currency/availability is not presented as a verified active offer.
- A retailer outage must not make search unavailable. Search returns the valid offers already stored, with freshness clearly represented.

This blueprint deliberately chooses background-only acquisition. It does not introduce request-time retailer fan-out.

## 2. Existing components to reuse

Do not rebuild these without a demonstrated gap:

- SQLAlchemy catalog models in `backend/app/models/catalog.py`.
- Alembic migrations in `backend/alembic/`.
- database URL validation and engine setup in `backend/app/db.py`.
- provider-neutral connector interface in `backend/app/connectors/base.py`.
- Notino authorized CJ/VIV feed adapter in `backend/app/connectors/notino_feed.py`.
- shared staging/matching/promotion path in `backend/app/services/connector_ingestion.py`.
- canonical matching and legacy ID mappings.
- current catalog-backed search API.
- all nine retailer scraper implementations and their fixtures.
- legacy public API/runtime until parity and rollback gates pass.

Existing code is a foundation, not proof of operational readiness. In particular, the current default catalog database is SQLite, the generic connector registry covers only five of nine retailers, and Notino currently uses a full-feed snapshot.

## 3. Target architecture

```text
Retailer sources
  |  scheduled / bounded acquisition only
  v
Connector adapters (one isolated adapter per retailer)
  |
  v
Durable job queue
  |-- discovery jobs
  |-- fetch/parse jobs
  |-- normalize + match jobs
  |-- validate + promote jobs
  |-- price/stock refresh jobs
  |-- retry / dead-letter jobs
  v
Raw ingestion evidence
  |
  v
Canonical identity resolution
  |-- GTIN exact match
  |-- stable retailer ID mapping
  |-- deterministic brand/name/concentration/size match
  |-- ambiguous -> review queue; never guess
  v
Offer validation and promotion
  |
  +--> offers + price_history + ingestion_runs + match_audit
  |
  v
Read-only catalog/search API
  |
  v
Frontend
```

## 4. Data and offer lifecycle

Canonical identity:
- Brand -> Fragrance -> ProductVariant.
- Variant identity includes concentration, size, tester/refill/gift-set/mini flags and GTIN where known.
- Keep canonical keys deterministic and unique.
- Do not merge variants based on title similarity alone.

Offer lifecycle:
- discovered -> staged -> normalized -> matched -> validated -> active.
- unresolved identity -> unmatched or review-required.
- invalid source data -> rejected/quarantined.
- expired freshness window -> stale/inactive for customer ranking.
- A retailer's absence from one feed snapshot must not immediately delete historical offer evidence.

Each offer must retain retailer, stable external ID, product URL, source provenance, price, explicit currency, availability, capture time, and validation/match confidence. Keep price history as immutable observations.

## 5. Retailer coverage

The intended retailer set remains:
Bplatz, Deloox, Easycosmetic, Notino, Orioudh, Parfumcity, Parfumzentrum, Perfumemarket, Sabina.

Build a registry with explicit capabilities and health state. Do not assume all nine are ready:
- Existing shared connector adapters: Notino plus legacy wrappers for Deloox, Easycosmetic, Parfumzentrum and Sabina.
- Bplatz, Orioudh, Parfumcity and Perfumemarket need adapter capability review before implementation.
- Preserve all current scraper code. Wrap existing implementations where safe; do not rewrite parsers just to fit the interface.
- Every adapter must have deterministic fixture tests for product identity, price/currency, stock states, malformed records, timeouts and changed source structure.

## 6. Persistence and concurrency decision

PostgreSQL is the target operational catalog database, but it is not proven to be the currently active production backend.

Before changing database configuration:
1. Collect a read-only production runtime report: active Fly machines, mounted volumes, configured database backend (backend name only), schema revision, and process/worker topology.
2. Verify backup and restore evidence for the current SQLite data volume.
3. Run migrations and import tests against a disposable PostgreSQL database.
4. Compare row counts, canonical identity counts, offer counts, constraints and search results.
5. Only then prepare a separately reviewed migration and rollback procedure.

Do not try to solve SQLite writer contention by increasing timeouts, restarting production, or launching another broad import. Do not run two independent SQLite writers against the same database file.

## 7. Worker and queue rules

Use the already-declared Celery/Redis dependencies only after verifying deployment topology and broker availability. Queue jobs must be idempotent and bounded.

Required controls:
- per-retailer concurrency and rate limits;
- connection/read timeouts;
- retry with capped exponential backoff and jitter;
- durable ingestion run records and progress counters;
- lease/visibility timeout or equivalent recovery for abandoned jobs;
- dead-letter queue with operator replay;
- connector circuit-breaker/quarantine and explicit reinstatement;
- per-job transaction boundaries; no network I/O while a DB transaction is open;
- graceful shutdown and bounded worker memory;
- structured logs with run/store/job IDs and no secrets.

Suggested cadence is configurable, not hard-coded:
- discovery: daily or retailer-specific;
- offer ingestion: retailer/feed-specific;
- price/stock refresh: more frequent for active offers;
- stale-offer expiry: scheduled and deterministic.

## 8. Search behavior

Search is a read-only query over canonical products and active offers:
- no network calls to retailers;
- no writes, ingestion, or queue waits;
- filter stale, rejected, quarantined and unmatched offers;
- rank by total payable price where shipping is known, availability, freshness, store reliability and match confidence;
- disclose missing shipping costs and uncertain stock rather than inventing them;
- return quickly even when every retailer is offline.

Search must have tests proving that connector methods are never invoked by the request path.

## 9. Delivery sequence and gates

### Gate A — runtime evidence (no production writes)
- obtain Fly machine/volume/process/database-backend report;
- verify backup/restore;
- map actual production entrypoint, public routes and workers;
- record baseline search latency and catalog/offer counts.

### Phase 1 — isolated persistence and migration proof
- use disposable PostgreSQL;
- run all current Alembic migrations;
- test seed/import from preserved JSON and legacy IDs;
- test uniqueness, foreign keys, transaction rollback and idempotent upserts;
- produce a parity report. No production cutover.

### Phase 2 — ingestion core hardening
- test raw staging, canonical matching, offer promotion, refresh and price history;
- make ingestion idempotent under duplicate/replayed jobs;
- add explicit stale/expiry semantics and audit transitions;
- add tests for concurrent independent workers.

### Phase 3 — connector registry and retailer adapters
- formalize capability registry and health states;
- bring each of the nine retailers behind the shared contract;
- add fixture/contract tests one retailer at a time;
- do not start broad live ingestion until each adapter passes offline tests.

### Phase 4 — durable worker orchestration
- introduce queues and isolated worker processes;
- prove retry, restart recovery, dead-letter replay, quarantine and per-store isolation;
- demonstrate that one failed retailer does not block others.

### Phase 5 — read-only search parity
- connect search only to canonical catalog and validated active offers;
- add tests that fail if search invokes network/connector code;
- compare results against the existing public search path.

### Phase 6 — shadow, canary and rollback
- run new search in shadow without changing customer responses;
- reconcile product identity, offer coverage, price, stock and latency;
- canary only after operator approval and verified rollback;
- keep legacy runtime until parity and rollback gates are met.

### Phase 7 — production cutover
- separate approval required;
- maintenance window, verified backup, migration, health checks and rollback;
- no automatic cutover from a CI workflow.

## 10. Non-negotiable safety boundaries

- Never edit or deploy `main` as part of this work.
- Never modify production Fly configuration, secrets, volumes or databases during branch development.
- Never trigger the Notino production import workflow as a test.
- Never merge or deploy without explicit approval.
- Never delete legacy runtime, retailer scrapers, catalog JSON, family registry, frontend, fixtures or operational workflows until parity and rollback are proven.
- Do not report a test as passed unless it was actually executed and its result inspected.

## 11. Immediate next implementation task

Start with Phase 1 in an isolated test environment: inspect every existing migration and model, create a disposable PostgreSQL test target, and prove the current schema/seed path before changing production-facing code. If a disposable PostgreSQL service cannot be provisioned by the available CI environment, stop at the reproducible test harness and report the exact external prerequisite; do not substitute SQLite and call it PostgreSQL validation.
