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
| 2 – Database & data model | PostgreSQL migrations repeat safely; canonical schema and seed are idempotent; runtime rejects unintended SQLite in staging; backup/restore | PostgreSQL 16 CI migration/seed gate and prior Neon staging infrastructure evidence; integrated gate still being stabilized; production remains on legacy SQLite | Partial |
| 3 – Canonical identity | Deterministic normalization; variant distinctions; GTIN and canonical-key rules; durable ambiguity review; repeatable backfill | Normalization, identity persistence and review-queue tests exist; combined integrated run must pass and data-quality thresholds remain to be measured | Partial |
| 4 – Universal connectors | Common contract; structured/API/feed preference; fixtures and contract tests per connector; rate/error handling; retailer authorization | Connector interface and offline fixtures exist for several stores; live feed authorization, terms review and complete connector coverage remain unverified | Partial |
| 5 – Ingestion pipeline | Scheduled discovery/refresh; separate match and promotion gates; idempotency; retry/backoff; raw evidence; DLQ and quarantine recovery | Celery tasks, ingestion workers, artifacts and dead-letter model exist; integrated runtime behavior and operational recovery still need acceptance | Partial |
| 6 – Matching & validation | GTIN/SKU/deterministic matching; confidence thresholds; unresolved review; strict publication validation; audit trail | Matching worker, persistence gates, canonical review queue and fixture vertical slice exist; complete matching cascade and production-quality precision/recall are not yet measured | Partial |
| 7 – Catalog-first search | Search reads only PostgreSQL canonical catalog and published offers; no retailer network calls in request path; real API response contract | PostgreSQL search route and frontend bridge exist; bridge is opt-in and defaults off; populated staging API and frontend integration remain unverified | Partial |
| 8 – Offer ranking & price history | Explainable ranking uses comparable currency, availability, freshness, store reliability, match confidence and shipping transparency; price history and trend tests | Price history persistence exists. Explainable ranking is being added on a separate draft branch; no acceptance until its tests and API integration pass | In progress |
| 9 – API & frontend | Real frontend uses PostgreSQL API; filters and empty states; stable schemas; staging end-to-end test | Search bridge and API compatibility tests exist, but no proof of a complete staging API/frontend pair on PostgreSQL | Partial |
| 10 – Observability & quality | Operational metrics for offers, freshness, connector health, matching, DLQ and latency; alert tests; admin review workflows | Legacy freshness diagnostic and several pipeline records exist; unified catalog-first metrics/admin workflow and integrated test suite are not yet accepted | Partial |
| 11 – Gradual migration | Old/new parallel comparison; measured quality/latency; staged traffic progression; rollback and recovery rehearsal | No verified catalog-first shadow comparison, progressive traffic rollout, or rollback rehearsal | Not started |

## Evidence already obtained

- A staging PostgreSQL database and isolated worker were previously deployed and inspected. At that time, the staging catalog had no configured stores and no published offers.
- An offline PostgreSQL vertical-slice fixture demonstrated ingestion → matching → promotion → price history/audit → HTTP API.
- A further fixture test demonstrated that the same offer is returned by the PostgreSQL catalog search endpoint.
- These fixtures prove a technical path, not live retailer coverage, real prices, freshness, or readiness for user testing.

## Release blockers

1. The integrated PostgreSQL/Redis CI workflow must pass as a single gate, with test isolation and compatibility checks fixed.
2. Offer ranking and its API/frontend representation must pass deterministic tests.
3. A staging API and frontend must be connected to the same populated PostgreSQL catalog.
4. At least one retailer data source must be explicitly authorized and configured before live operational verification. Until then, use offline fixtures only.
5. Metrics, alerts, quarantine and human review must be usable end-to-end.
6. Shadow comparison, staged rollout and rollback must be demonstrated without exposing users to incomplete catalog data.

**No phase is marked complete by this matrix.** Update a phase to complete only when links to passing CI runs, relevant integration evidence, and operational acceptance are attached.
