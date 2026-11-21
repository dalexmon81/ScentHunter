# ScentHunter catalog-first migration

## Repository state and safety contract

This document describes the catalog-first work already present in the repository. The current isolated cleanup branch is `architecture/offer-first-v2`; protected `main` remains untouched. Repository cleanup must be completed and explicitly approved before any new architecture implementation begins.

The repository already contains substantial catalog-first work. Do not recreate or overwrite these components without first reviewing and extending them:

- `backend/app/`: package with API, config, connectors, models, repositories, schemas, search, services and workers directories.
- `backend/alembic/`: migrations `0001_initial_catalog_schema.py`, `0002_ingestion_raw.py`, and `0003_store_domain.py`.
- `backend/scenthunter_next_engine/`: canonical matcher, catalog repository, migration planning/audit, offer normalization/aggregation, runtime and Phase 0 baseline jobs.
- `backend/phase0_baseline_worker.py`: durable Phase 0 worker.
- `backend/product_catalog.json` and `backend/family_registry.json`: current legacy source artifacts; preserve them as migration inputs.
- `tools/diagnostics/` and `tools/debug/`: diagnostic assets already organized outside the backend package.
- `.github/workflows/phase-0-live-baseline.yml`: existing baseline workflow.

The legacy runtime remains important for compatibility. This work must be additive and staged. Never delete or rename legacy modules, JSON inputs, scraper modules, diagnostic scripts, database volumes, or production workflows as part of a structural-only commit.

## Verified current inventory (2026-11-18)

> Historical snapshot: the inventory below records the repository state observed on 2026-11-18. It is not a claim that every listed path, byte count, branch name or runtime detail remains current. Recheck the live tree and deployment configuration before acting on it.


Repository: `dalexmon81/ScentHunter`

Protected default branch: `main`

Working branch: `refactor/catalog-first-architecture`

Legacy core files on main:
- `backend/main.py` — 241,075 bytes
- `backend/catalog_engine.py` — 337,477 bytes
- `backend/product_matcher.py` — 140,062 bytes
- `backend/product_catalog.json` — 1,242,247 bytes
- `backend/offer_engine/refresh_worker.py` — present
- `backend/family_registry.json` — present

Existing store scraper packages:
- bplatz
- deloox
- easycosmetic
- notino
- orioudh
- parfumcity
- parfumzentrum
- perfumemarket
- sabina

Diagnostics are already under `tools/diagnostics/`; debug helpers are already under `tools/debug/`. Some diagnostics are referenced by tests or workflows. Move/delete only after dependency and CI reference scans, and only with a replacement or explicit retirement decision.

## Guiding runtime invariant

Normal user search must query only the internal canonical catalog and published, sufficiently fresh offers. It must not trigger retailer discovery or broad live scraping.

Store discovery, ingestion, normalization, matching, validation and offer refresh happen in background workers. A product-page refresh may be a narrowly bounded operation only when explicitly designed and rate limited; it must not turn search into live crawling.

An offer is publishable only when it has a traceable source/store, a valid product URL, positive price, ISO currency, explicit availability, a trustworthy match to a canonical variant, and an acceptable freshness timestamp. Ambiguous matches are held for review, not guessed.

## Existing schema and migration notes

The initial migration already defines brands, fragrances, product_variants, stores, offers, price_history, match_audit and ingestion_runs. Later migrations add raw ingestion and store-domain fields. SQLAlchemy models include legacy ID mapping tables. Review all current migrations/models before changing schema.

Important extension points to verify before Phase 2 is called complete:
- canonical variant identity and GTIN uniqueness policy (including null/invalid GTIN handling)
- explicit variant format flags (tester/refill/gift set/mini) and unknown-vs-false semantics
- offer state machine and stale/quarantined/rejected states
- raw payload retention policy, redaction, size limits and retention
- uniqueness for store + external product identity and idempotent re-ingestion
- database URL handling, PostgreSQL deployment and rollback strategy
- currency/price constraints and availability vocabulary
- referential integrity and migration compatibility with SQLite/local test environments

Do not run production migrations or data promotion from this branch without a reviewed backup, staging verification, and an explicit rollout procedure.

## Phases and exit criteria

### Phase 0 — safety and measurable baseline

1. Confirm this branch is based on the current protected-main history; keep all work isolated.
2. Preserve copies of catalog JSON, family registry, connector settings and relevant fixtures before data conversion.
3. Inventory every connector and record its supported markets, discovery/product/offer endpoints, data fields, variant extraction, availability extraction, source type, rate limits and known failure modes.
4. Run the existing Phase 0 baseline workflow/worker in read-only mode. Capture product count, offers by store, valid price/URL/availability ratios, freshness distribution, unmatched and ambiguous counts, and store health.
5. Save timestamped CSV/JSON outputs as CI artifacts or protected operational artifacts; avoid committing live customer or retailer payloads.

Exit: repeatable baseline report exists, each store has an owner/health status, input data is backed up, and no production state was changed.

### Phase 1 — repository organization and boundaries

The target responsibilities are:
- API: HTTP contracts and authentication/authorization.
- Services: business orchestration.
- Repositories: persistence and query implementation.
- Models/schemas: database entities and API contracts.
- Connectors: store-specific discovery/fetch/parse adapters.
- Workers: asynchronous ingestion, validation and refresh.
- Matching: deterministic and assisted identity resolution.
- Search: catalog-only query and ranking.

The repository already has much of this layout under `backend/app/`. First map each existing module to a responsibility and close missing pieces; do not create duplicate package trees. Diagnostic files already live in `tools/diagnostics/` and `tools/debug/`. Scan imports, endpoint mounting, tests, CI workflows, scripts and deployment manifests before moving or retiring any of them.

Exit: architecture map and import/dependency inventory are committed; no production code moves without passing import, unit and deployment checks.

### Phase 2 — data model and PostgreSQL

Review existing Alembic revisions and SQLAlchemy models rather than generating duplicate tables. Validate the canonical data model:
- brands
- fragrances
- product_variants
- stores
- offers
- price_history
- match_audit
- ingestion_runs
- raw ingestion payloads and legacy ID maps

Canonical product identity is separate from retailer offers. EDP/EDT/Parfum/Extrait, bottle size, tester, refill, gift set and mini must remain distinct variant attributes. Keep unknown metadata distinct from an explicit false value.

Use PostgreSQL as the target source of truth. Retain JSON catalog files as immutable migration inputs until reconciliation and rollback windows close. Validate indexes, constraints, uniqueness and idempotency with staging data.

Exit: migration tests pass on an empty database and a realistic copy; legacy IDs reconcile; migration and rollback have been rehearsed; no production data loss.

### Phase 3 — normalization and canonical identity

Implement deterministic normalization with versioned rules:
- Unicode normalization, case folding, whitespace and punctuation handling.
- curated brand aliases (e.g. Dior / Christian Dior) rather than blind rewriting.
- base fragrance name separated from concentration, volume and format.
- explicit variant attributes for EDP, EDT, Parfum, Extrait, Cologne, sizes and kits.
- stable canonical key derived from normalized identity fields.

GTIN is a strong identifier only after syntax/check-digit validation and collision checks. A matching GTIN must not silently override conflicting brand, fragrance, concentration or package details. Deterministic key collisions and inconsistent metadata go to review.

Exit: golden fixtures cover aliases, accents, sizes, concentration, tester/refill/gift-set/mini and conflicting GTINs; normalization is repeatable and versioned.

### Phase 4 — store connectors

Define a typed connector contract for discovery, product fetch, offer fetch, price/stock refresh, parsing, normalization and validation. Standardize retry/backoff, timeouts, rate limits, logging, metrics and store-level quarantine.

Prefer official/affiliate APIs and feeds, then structured data/JSON-LD, then stable JSON endpoints, HTML parsing and finally browser automation. Document the legal/contractual basis and access limits for each source.

Every connector needs offline fixtures for normal product, variants, out-of-stock, missing price, missing URL, missing stock, malformed payload and upstream layout/schema changes. One connector failure must not block other stores.

Exit: connector contract tests run independently, fixtures are versioned and ingestion errors are isolated per store.

### Phase 5 — ingestion pipeline and workers

Implement idempotent jobs for discovery, raw capture, normalization, matching, validation, publication, price/stock refresh, retry and dead-letter processing. Choose one queue/workflow technology based on existing deployment constraints; do not introduce Redis/Celery or Temporal until the current worker/queue architecture and persistence model are assessed.

Preserve raw payloads with bounded size, access control and retention. Use exponential backoff with jitter, explicit retry ceilings, per-store concurrency limits and quarantine thresholds.

Suggested initial cadence is configurable per store: daily discovery, 6–12 hour offer refresh, and 15–60 minute price/stock checks only for high-value stores where permitted and operationally sustainable. These are starting policies, not hard-coded assumptions.

Exit: jobs are durable, idempotent, observable, replayable and unable to block one another across stores.

### Phase 6 — matching and validation

Matching cascade:
1. Validated GTIN exact match, subject to collision/conflict checks.
2. Previously reviewed store + external-product mapping.
3. Deterministic normalized brand/name/concentration/size/format.
4. Optional semantic assistance that can propose candidates but cannot auto-publish without guardrails.
5. Human review for low-confidence or conflicting candidates.

Persist method, confidence, evidence and decision in audit history. Separate candidate match from accepted match. Reject or quarantine offers with invalid price/currency/URL, missing explicit availability, expired timestamps, invalid store status or unresolved product identity.

Confidence thresholds must be calibrated on labeled examples, not chosen arbitrarily.

Exit: precision/recall measured on a labeled set; ambiguous matches cannot leak into published search results.

### Phase 7 — catalog-only search

Search canonical entities and currently published offers only. Start with PostgreSQL full-text/search indexes if they meet latency and typo-tolerance goals. Add a dedicated engine only after load testing demonstrates a need.

Filters: brand, fragrance, concentration, size/format, family, gender, price, store, country, currency and availability. Return offer timestamps and freshness state.

Exit: tests prove search endpoints never call connector discovery or retailer scraping; search latency and result quality meet agreed targets.

### Phase 8 — offer ranking and price history

Rank using total cost, availability, freshness, store reliability, match quality and shipping transparency. Never sort on base price alone when shipping/tax differ. Preserve user-visible source and last-updated time. Derive historic minima/averages only from valid comparable observations in the same currency/variant.

Exit: deterministic ranking tests and time-series integrity checks pass.

### Phase 9 — API and frontend migration

Introduce stable typed API contracts while preserving legacy endpoints during migration. Update frontend for fresh/stale/unavailable offers, store filters, no-offer states and source transparency.

Exit: contract tests pass, legacy clients remain compatible, and a feature flag can revert traffic safely.

### Phase 10 — observability and quality

Track ingestion volume, published/rejected/quarantined offers, valid field ratios, match quality, freshness, per-store failure rates, retry/dead-letter counts, search latency and connector throughput. Alert on connector regressions and stale offers. Keep sensitive raw payloads out of logs.

Exit: dashboards, alerts, runbooks and regression suites are available before any production cutover.

### Phase 11 — gradual migration

Run old and new read paths in shadow mode, compare result coverage, prices, match quality, errors and latency, then increase traffic gradually (e.g. 5/20/50/100%) only after gates pass. Keep rollback and data reconciliation ready. Avoid dual-writer conflicts; designate a single authoritative writer per table.

Exit: each traffic step is approved by measured parity and rollback remains tested.

### Phase 12 — scale and add stores

Add stores through the connector contract only. Require test coverage, sufficient completeness, measured match precision and stable error rate before publication. Expand markets/currencies only with localization, shipping and legal/source review.

Exit: new connectors are isolated, reviewed, observable and independently quarantinable.

## Definition of done

- Search reads the internal catalog and published offers only.
- Canonical identities and commercial variants are distinct.
- Every published offer is traceable, fresh, purchasable and safely matched.
- Store integrations are isolated and testable.
- Raw ingestion is replayable under retention controls.
- Price history and match audit are reliable.
- Failed stores do not block healthy stores.
- Metrics, alerts, runbooks and staged rollback exist.
- Legacy JSON files are retained as seed/rollback artifacts until reconciliation is complete.
