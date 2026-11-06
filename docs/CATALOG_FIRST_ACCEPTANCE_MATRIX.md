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
| 0 – Preparation & safety | Reproducible backup/restore; supported-store inventory; baseline coverage report; documented safe test targets | Existing preparation notes and staging setup evidence; full backup/restore and baseline evidence still needs consolidation | Partial |
| 1 – Repository cleanup | Clear module boundaries; legacy diagnostics outside production path; dependency/import checks; no accidental runtime coupling | New app/API/services/connectors/workers structure exists, but large legacy modules remain and separation is not fully demonstrated | Partial |
| 2 – Database & data model | PostgreSQL migrations repeat safely; canonical schema and seed are idempotent; runtime rejects unintended SQLite in staging; backup/restore | PostgreSQL 16/Redis integrated CI passed migrations twice, canonical seed and schema checks in [run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). Prior isolated Neon staging worker evidence exists. Production still uses legacy SQLite; backup/restore remains outstanding | Partial |
| 3 – Canonical identity | Deterministic normalization; variant distinctions; GTIN and canonical-key rules; durable ambiguity review; repeatable backfill | Identity, normalization, review queue and matching suites passed in [integrated run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). Real-catalog precision/recall thresholds remain unmeasured | Partial |
| 4 – Universal connectors | Common contract; structured/API/feed preference; fixtures and contract tests per connector; rate/error handling; retailer authorization | Connector contracts and offline fixtures passed in [integrated run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). Live feed authorization, retailer terms and full store coverage remain unresolved; no retailer is activated | Partial |
| 5 – Ingestion pipeline | Scheduled discovery/refresh; separate match and promotion gates; idempotency; retry/backoff; raw evidence; DLQ and quarantine recovery | Worker, Celery/Redis, matching, promotion, queue and dead-letter suites passed in [integrated run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413); prior isolated staging worker ping/queued-task smoke passed. Real retailer refresh/recovery remains unverified | Partial |
| 6 – Matching & validation | GTIN/SKU/deterministic matching; confidence thresholds; unresolved review; strict publication validation; audit trail | Matching, validation, review queue and fixture vertical slice passed in [integrated run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). Real-catalog precision/recall and human review operations remain unmeasured | Partial |
| 7 – Catalog-first search | Search reads only PostgreSQL canonical catalog and published offers; no retailer network calls in request path; real API response contract | PostgreSQL search API and ingestion-to-search fixture path passed in [integrated run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). New route remains opt-in/default off; populated staging API/frontend integration is not yet proven | Partial |
| 8 – Offer ranking & price history | Explainable ranking uses comparable currency, availability, freshness, store reliability, match confidence and shipping transparency; price history and trend tests | Ranking is integrated into PostgreSQL search and the frontend display; ranking/API and broader vertical-slice tests passed in [run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). Real populated-catalog and staging validation remain | Partial |
| 9 – API & frontend | Real frontend uses PostgreSQL API; filters and empty states; stable schemas; staging end-to-end test | Frontend sends a stable canary cohort header and renders ranking explanations; API, frontend contract and rollout tests passed in [run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). Catalog route remains disabled by default and staging integration remains unverified | Partial |
| 10 – Observability & quality | Operational metrics for offers, freshness, connector health, matching, DLQ and latency; alert tests; admin review workflows | Authenticated metrics, identity/match review queues and dead-letter visibility passed in [run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). Live staging population, alert delivery and operator runbooks remain | Partial |
| 11 – Gradual migration | Old/new parallel comparison; measured quality/latency; staged traffic progression; rollback and recovery rehearsal | Stable cohorts, explicit percentage gating, background non-serving shadow reads and comparison tests passed in [run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). No real shadow traffic, canary percentage, populated staging comparison or rollback rehearsal has been authorized/performed | Partial |

## Latest integrated acceptance evidence (2026-11-06)

- The combined PostgreSQL 16/Redis workflow passed migrations, seed, schema, identity, connectors, ingestion, matching, vertical slice, catalog search API, admin metrics/review/dead-letter routes, rollout/shadow tests, frontend cohort-header check, and the offline retailer-credential boundary: [run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413).
- The rollout master switch alone is now fail-closed at 0%; a traffic percentage must be explicitly configured before catalog requests can be served.
- Shadow reads execute in a background thread, so the legacy `/search-start` response does not wait for the non-serving catalog lookup.
- CI uses disposable PostgreSQL and local fixtures. It is not evidence of live retailer coverage, current prices, populated staging, or production readiness.

## Evidence already obtained

- A staging PostgreSQL database and isolated worker were previously deployed and inspected. At that time, the staging catalog had no configured stores and no published offers.
- An offline PostgreSQL vertical-slice fixture demonstrated ingestion → matching → promotion → price history/audit → HTTP API.
- A further fixture test demonstrated that the same offer is returned by the PostgreSQL catalog search endpoint.
- These fixtures prove a technical path, not live retailer coverage, real prices, freshness, or readiness for user testing.

## Release blockers

1. A reproducible backup/restore rehearsal and consolidated Phase 0 baseline are still required.
2. A staging API and frontend must be connected to the same populated PostgreSQL catalog.
3. At least one retailer data source must be explicitly authorized and configured before live operational verification. Until then, use offline fixtures only.
4. Metrics, alert delivery, quarantine recovery and human review must be exercised operationally.
5. Shadow comparison, staged rollout and rollback must be demonstrated against populated staging data after explicit approval.
6. Repository modularization and the remaining legacy/production database separation still require acceptance.

**No phase is marked complete by this matrix.** Update a phase to complete only when links to passing CI runs, relevant integration evidence, and operational acceptance are attached.
