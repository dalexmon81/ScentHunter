# ScentHunter — 12-phase architecture completion roadmap

## Purpose and delivery boundary

The immediate objective is to prepare and verify the complete catalog-first architecture across all 12 phases. This is an engineering/readiness programme, not a production rollout.

**Until the architecture programme is accepted, do not deploy, migrate persistent production data, activate retailers, change production flags or traffic, run live retailer ingestion, or conduct a production cutover.** Use repository review, unit/integration/contract tests, offline fixtures, and disposable CI services.

After all 12 architecture phases have passed their exit criteria, prepare a separate production-readiness decision and execute production rollout only with explicit approval.

## What “architecture complete” means

For each phase, the repository must contain the relevant implementation, contracts, tests, documentation, observability hooks, failure handling and safe operational runbook. A passing fixture test proves code behaviour under that fixture; it does not prove live retailer access, populated staging, production reliability or permission to operate.

Phase 11 and Phase 12 are included now as architecture deliverables: rollout/rollback mechanisms and scaling/multi-store extension design must be implemented and tested in disposable environments. Their production execution remains deferred.

## Phase gates

### Phase 0 — Preparation, inventory and safety
- Maintain the agreed nine-retailer inventory and distinguish connector code from permission and live evidence.
- Define baseline schema, deterministic quality validation, architecture-vs-operations gates, CI backup/restore.
- Exit: inventory, baseline contract, validator and disposable restore test are complete and green.
- Known integration issue to resolve: the baseline worker currently reads the legacy SQLite catalog rather than the canonical catalog source selected by the final architecture.

### Phase 1 — Repository and application boundaries
- Continue extracting the monolithic `backend/main.py` into API, services, repositories, connectors, workers, matching, search, config and schemas.
- Keep API handlers thin; services own use cases; repositories own persistence; connectors never leak into user-search handlers.
- Mount and test the canonical API routers through the real application factory.
- Exit: application composition is explicit, import boundaries are tested, legacy compatibility is isolated, and no user-search route invokes retailer discovery/refresh.

### Phase 2 — Database and canonical data model
- Complete database abstraction, supported PostgreSQL runtime, Alembic schema parity, transaction/constraint tests and runtime identity proof.
- Build dry-run-first, resumable, idempotent canonical SQLite-to-PostgreSQL importer with count/checksum/FK reconciliation.
- Preserve legacy retailer SQLite as a separate system; never silently repoint it.
- Exit: disposable PostgreSQL migration/import/rollback tests are green. Production cutover is not part of this gate.

### Phase 3 — Product normalization and variants
- Normalize brand, fragrance, concentration, size, tester/refill/gift-set and GTIN without losing source evidence.
- Define deterministic canonical keys, deduplication and conflict handling.
- Add regression fixtures for ambiguous and incomplete product descriptions.
- Exit: normalization is deterministic, idempotent and tested; variants remain distinct.

### Phase 4 — Universal retailer connectors
- Standardize connector interface, runtime registry, configuration, source evidence and connector contract tests.
- Prefer authorized structured APIs/feeds; HTML parsing is a controlled fallback. Respect 403/429, challenges and site access rules; never bypass them.
- Test all nine adapters offline, including malformed payloads, timeouts, missing fields and schema drift.
- Exit: adapters conform to contracts and failures are isolated. Connector presence does not mean authorization or activation.

### Phase 5 — Background ingestion pipeline
- Complete queue/task lifecycle: discovery, fetch, raw evidence, normalize, validate, match, publish, refresh, retry, dead-letter and quarantine.
- Ensure idempotency, bounded retries, immutable evidence, per-store isolation and explicit scheduling configuration.
- Verify real PostgreSQL + Redis + Celery worker execution using disposable CI services.
- Exit: end-to-end fixture pipeline and recovery paths pass without API-process scraping.

### Phase 6 — Matching and offer validation
- Implement a conservative cascade: GTIN, trusted retailer SKU mapping, deterministic brand/name/concentration/size, then optional semantic candidate ranking with human review for ambiguity.
- Persist match evidence, confidence, audit history and review decisions.
- Enforce required offer evidence: product/variant, retailer, URL, positive price, currency, availability, timestamps, freshness and source.
- Exit: precision/recall fixture suite, false-positive controls, audit and review queue tests pass. No ambiguous offer is auto-published.

### Phase 7 — Catalog-first search
- Complete PostgreSQL search/index contract, filters, sorting, pagination and response compatibility.
- Ensure search reads only canonical identities and published, fresh offers; no live retailer lookup, discovery or refresh in request path.
- Wire the production application route only after compatibility and isolation tests are complete; keep rollout flag default-safe.
- Exit: API integration tests prove empty catalog, identity-only results, active/stale/inactive offers, typo/token behaviour and no connector calls.

### Phase 8 — Offer ranking and price history
- Rank by comparable delivered price when known, availability, retailer reliability, freshness and match quality; unknown shipping must not be treated as zero.
- Store price observations/history and expose transparent ranking factors.
- Exit: ranking invariants, currency separation, unknown-cost behaviour, stale offer handling and history tests pass.

### Phase 9 — API and frontend integration
- Finalize typed request/response contracts, pagination, filters, error states, identity-only/no-offer states and offer refresh detail flow.
- Remove reliance on accidental legacy payload fields; keep a tested compatibility adapter during migration.
- Exit: backend/frontend contract and end-to-end tests pass against a populated disposable PostgreSQL catalog.

### Phase 10 — Observability, quality and operator controls
- Add per-store ingestion, offer quality/freshness, matching, search latency, queue age, retry, dead-letter, quarantine and publication metrics.
- Add actionable alerts, audit trail, operator review, replay/recovery and documented runbooks.
- Exit: deterministic alert/recovery simulations and admin authorization tests pass in CI; live alert delivery remains a later operational check.

### Phase 11 — Rollout, shadow comparison and rollback architecture
- Implement release toggles, deterministic cohort selection, shadow comparison, parity reports, canary decision rules and immediate rollback path.
- Define thresholds and stop conditions for result parity, errors, latency, offer coverage and data quality.
- Test shadow/canary/rollback logic with synthetic traffic and disposable services only.
- Exit: automated rollout decision tests and rollback procedure are reviewed and pass. No production traffic is shifted during architecture preparation.

### Phase 12 — Scale and retailer/country expansion architecture
- Make connector onboarding repeatable through contracts, configuration validation, per-store limits, isolation, quarantine and quality gates.
- Define country/currency/shipping/tax/localization boundaries, rate limits, capacity planning, queue partitioning and index growth strategy.
- Test multiple synthetic retailers/countries, partial outages, backpressure and recovery.
- Exit: expansion checklist, load/failure tests and capacity assumptions are documented and reproducible. No new live retailer is activated during architecture preparation.

## Current known gaps to keep visible

- `backend/main.py` remains a large legacy application module; extraction is incremental.
- The new catalog search route exists and is mounted, but legacy search compatibility and actual default route behaviour must be verified before changing traffic.
- The canonical database runtime and production database state must not be assumed equivalent; PostgreSQL support/import/cutover require their own evidence.
- The Phase 0 baseline worker still reads legacy SQLite; it must be reconciled with the canonical catalog source.
- Retailer authorization and live offer evidence are operational prerequisites, not architecture prerequisites.
- CI disposable backup/restore is not a persistent staging backup/restore rehearsal.

## Execution order and acceptance

Work proceeds sequentially through Phases 0–12, with cross-phase regression tests after each integration. A phase is not complete because a document or module exists: its exit criteria must be backed by code, tests and review evidence.

At the end of Phase 12, produce an architecture acceptance report listing each phase as PASS / PARTIAL / BLOCKED with links to commits, tests and unresolved risks. Only then prepare a separate production plan covering credentials/permissions, persistent staging rehearsal, real offer baseline, alert delivery, controlled deployment, data migration, canary and rollback. Production begins only after explicit user approval.
