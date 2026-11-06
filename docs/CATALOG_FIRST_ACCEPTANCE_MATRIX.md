# Catalog-first acceptance matrix (Phases 0–11)

This matrix is deliberately evidence-based. A directory, endpoint, green isolated test, or fixture does not by itself mark a phase complete.

## Completion rule

A phase can be accepted only when all three are demonstrated on the same integrated release candidate:

1. **Implemented** — production code and configuration are present.
2. **Verified** — automated tests and the relevant integration/operational checks pass.
3. **Connected** — the feature is exercised through the real adjacent components, not only as an isolated unit.

The overall ScentHunter trial remains blocked until every phase below is accepted and the release candidate passes the authorized operational and migration checks. No live retailer access, staging deployment, feature-flag activation, or production rollout is authorized by this document.

| Phase | Acceptance evidence required | Current evidence / remaining blocker | Status |
|---|---|---|---|
| 0 – Preparation & safety | Reproducible backup/restore; supported-store inventory; baseline coverage report; documented safe test targets | Disposable PostgreSQL backup/restore rehearsal passed in [integrated run 42179338407](https://github.com/dalexmon81/ScentHunter/actions/runs/42179338407). Actual staging/production restore, a single consolidated nine-store inventory, and a complete baseline with coverage/quality counts are still missing | Partial |
| 1 – Repository cleanup | Clear module boundaries; legacy diagnostics outside production path; dependency/import checks; no accidental runtime coupling | New modular structure exists, but the active `backend/main.py` is still about 245 KB and mounts many `diagnose_*` routers while retaining legacy search/orchestration code. Module boundaries and diagnostic isolation are not accepted | Partial |
| 2 – Database & data model | PostgreSQL migrations repeat safely; canonical schema and seed are idempotent; runtime rejects unintended SQLite in staging; backup/restore | PostgreSQL 16/Redis CI and isolated staging worker evidence exist. However the user-facing legacy catalog engine in `main.py` still reads its SQLite catalog; the PostgreSQL catalog is a separate opt-in path. Staging/production restore and proof that all catalog services share the intended PostgreSQL identity remain outstanding | Partial |
| 3 – Canonical identity | Deterministic normalization; variant distinctions; GTIN and canonical-key rules; durable ambiguity review; repeatable backfill | Identity, normalization, review queue and matching suites passed in [integrated run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). Real-catalog precision/recall thresholds remain unmeasured | Partial |
| 4 – Universal connectors | Common contract; structured/API/feed preference; fixtures and contract tests per connector; rate/error handling; retailer authorization | Connector contracts and offline fixtures passed in [integrated run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). No source is currently proven authorized for live ingestion: Bplatz permission is pending, Notino.fr CJ approval/feed entitlement is pending, and Deloox has a prior HTTP 403. Store coverage and permitted access remain unresolved | Partial |
| 5 – Ingestion pipeline | Scheduled discovery/refresh; separate match and promotion gates; idempotency; retry/backoff; raw evidence; DLQ and quarantine recovery | Worker, Celery/Redis, matching, promotion, queue and dead-letter suites passed in [integrated run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413); isolated staging worker ping/queued-task smoke passed. Staging readiness still reports `stores=0` and `offers=0`; no authorized real offer has completed ingestion, refresh, persistence and recovery | Partial |
| 6 – Matching & validation | GTIN/SKU/deterministic matching; confidence thresholds; unresolved review; strict publication validation; audit trail | Matching, validation, review queue and fixture vertical slice passed in [integrated run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). Real-catalog precision/recall and human review operations remain unmeasured | Partial |
| 7 – Catalog-first search | Search reads only PostgreSQL canonical catalog and published offers; no retailer network calls in request path; real API response contract | PostgreSQL route and fixture path pass in CI, but rollout remains disabled by default and the frontend's `/search-start` still uses the legacy SQLite catalog unless an explicit PostgreSQL canary is enabled. Audit also found a live Notino bridge and a legacy live-adapter fallback in the search path. Fail-closed correction is now committed (`aee40c1`) with regression tests; CI result is still pending. Populated staging API/frontend proof remains missing | Partial |
| 8 – Offer ranking & price history | Explainable ranking uses comparable currency, availability, freshness, store reliability, match confidence and shipping transparency; price history and trend tests | Ranking is integrated into PostgreSQL search and the frontend display; ranking/API and broader vertical-slice tests passed in [run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). Real populated-catalog and staging validation remain | Partial |
| 9 – API & frontend | Real frontend uses PostgreSQL API; filters and empty states; stable schemas; staging end-to-end test | Frontend sends the stable cohort header and renders ranking explanations, but its normal `/search-start` journey is not yet proven against the PostgreSQL API. With the rollout switch at 0%, it remains on the legacy catalog path. Full populated-staging user journey, filters, empty/error states and mobile acceptance remain unverified | Partial |
| 10 – Observability & quality | Operational metrics for offers, freshness, connector health, matching, DLQ and latency; alert tests; admin review workflows | Authenticated metrics, identity/match review queues and dead-letter visibility passed in [run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). Live staging population, alert delivery, operator-runbook execution, quarantine recovery and staging/production restore evidence remain | Partial |
| 11 – Gradual migration | Old/new parallel comparison; measured quality/latency; staged traffic progression; rollback and recovery rehearsal | Stable cohorts, explicit percentage gating, background non-serving shadow reads and comparison tests passed in [run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). No real shadow traffic, canary percentage, populated staging comparison or rollback rehearsal has been authorized/performed | Partial |

## Latest integrated acceptance evidence (2026-11-06)

- The same integrated workflow now includes a guarded `pg_dump`/`pg_restore` rehearsal. It creates and removes only a `ci_restore_*` database on loopback PostgreSQL, compares catalog row counts and Alembic revision, and passed as part of [run 42179338407](https://github.com/dalexmon81/ScentHunter/actions/runs/42179338407). This does not back up or restore staging/production.


- The combined PostgreSQL 16/Redis workflow passed migrations, seed, schema, identity, connectors, ingestion, matching, vertical slice, catalog search API, admin metrics/review/dead-letter routes, rollout/shadow tests, frontend cohort-header check, and the offline retailer-credential boundary: [run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413).
- The rollout master switch alone is now fail-closed at 0%; a traffic percentage must be explicitly configured before catalog requests can be served.
- Shadow reads execute in a background thread, so the legacy `/search-start` response does not wait for the non-serving catalog lookup.
- CI uses disposable PostgreSQL and local fixtures. It is not evidence of live retailer coverage, current prices, populated staging, or production readiness.

## Evidence already obtained

- A staging PostgreSQL database and isolated worker were previously deployed and inspected. At that time, the staging catalog had no configured stores and no published offers.
- An offline PostgreSQL vertical-slice fixture demonstrated ingestion → matching → promotion → price history/audit → HTTP API.
- A further fixture test demonstrated that the same offer is returned by the PostgreSQL catalog search endpoint.
- These fixtures prove a technical path, not live retailer coverage, real prices, freshness, or readiness for user testing.

## Repository audit findings (2026-11-06)

The repository audit of the integrated Phase 10 branch confirmed these cross-phase blockers:

- The frontend search calls `/search-start`. That route serves PostgreSQL only when the explicit catalog rollout decision selects it; with the master switch/traffic percentage at zero, the legacy SQLite catalog remains the serving path.
- The legacy application remains a large monolith and still mounts diagnostic routers in `backend/main.py`; Phase 1 is not accepted.
- The isolated PostgreSQL engine supports a required-PostgreSQL guard, but that does not migrate the legacy SQLite catalog or prove every runtime is using one PostgreSQL catalog.
- The staging readiness record reports 60 brands, 1,389 fragrances and 512 variants, but zero configured stores and zero offers. This is useful catalog seed evidence, not a populated offer catalog.
- The search-path safety correction in commit `aee40c158f8f9b96c692f5ca560bdc9aefbe396d` disables foreground retailer refresh/live fallback and returns an explicit error when the catalog engine is unavailable. Regression tests were added in `backend/tests/test_catalog_search_fail_closed.py` and wired into the vertical-slice workflow. The commit has not yet been confirmed by a completed CI run.
- PR #374 remains a draft and is one commit behind its base branch; no rebase, merge, deployment, staging audit, retailer request or traffic change was performed during this audit.

## Release blockers

1. A real staging/production backup and restore rehearsal, plus the consolidated Phase 0 baseline and source inventory, are still required.
2. A staging API and frontend must be connected to the same populated PostgreSQL catalog.
3. At least one retailer data source must be explicitly authorized and configured before live operational verification. Until then, use offline fixtures only.
4. Metrics, alert delivery, quarantine recovery and human review must be exercised operationally.
5. Shadow comparison, staged rollout and rollback must be demonstrated against populated staging data after explicit approval.
6. Repository modularization and the remaining legacy/production database separation still require acceptance.

**No phase is marked complete by this matrix.** Update a phase to complete only when links to passing CI runs, relevant integration evidence, and operational acceptance are attached.


### Follow-up audit corrections (2026-11-06)

- Connector currency validation previously hard-coded EUR. The connector and Celery validation gates now share a normalized three-letter currency-code check; store/marketplace currency support still requires an explicit supported-currency policy before publication. This is syntax validation, not a claim that every possible three-letter code is an assigned ISO 4217 currency.
- Connector validation previously allowed `unknown` availability although persistence promotion rejected it. Unknown stock is now rejected before matching; `in_stock`, `out_of_stock`, and `preorder` remain explicit states.
- Canonical variant `size_ml` previously used an integer column despite normalization supporting fractional ml values (for example oz conversion). The model now uses `Numeric(8,2)` with a forward Alembic migration; existing integer values are preserved.
- Offline regression coverage added for currency syntax, publishable availability states, and fractional size precision. These changes are not applied to any live database until an explicitly authorized migration.

- The PostgreSQL Bplatz hydration preflight maintained an exact allow-list of Alembic revisions and therefore rejected the newly added `0008_variant_size_precision` even when all required tables were present. The read-only preflight allow-list now includes the new head; this was found by the disposable PostgreSQL CI run, not by a live environment check.

- The first SQLite compatibility run exposed that the size migration used native `ALTER COLUMN TYPE`, which SQLite does not support. The migration now uses Alembic batch alteration so the same revision can rebuild the SQLite table in disposable tests and use the PostgreSQL type alteration in the canonical CI database. The corrected migration must pass the full CI run before it is accepted.

- Discovery completion now updates the exact `IngestionRun.id` created by that task instead of selecting the newest running run for a store. This removes a concrete cross-run race, but still needs a concurrency regression test.
- Worker validation now compares the payload's store key with the persisted `Store.slug`; mismatched attribution is rejected before matching.
- The fractional-size migration is explicitly dialect-aware: SQLite uses Alembic table recreation, PostgreSQL uses `ALTER COLUMN ... TYPE NUMERIC(10,4)`. Disposable CI exposed the SQLite incompatibility in the first implementation; the corrected migration is awaiting a fresh full run.
- Connector payload validation retains `unknown` stock as evidence but blocks it from entering the match/promotion path; the Notino preflight keeps such a candidate in an availability-review state.
- `is_currency_code` currently validates the normalized three-letter shape only. It does not prove that a code is assigned in ISO 4217; a shared supported-currency registry remains a required follow-up before enabling additional markets.
