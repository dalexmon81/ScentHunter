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
| 2 – Database & data model | PostgreSQL migrations repeat safely; canonical schema and seed are idempotent; runtime rejects unintended SQLite in staging; backup/restore | PostgreSQL 16 + Redis integrated CI passed migrations twice and canonical seed on run [42177330555](https://github.com/dalexmon81/ScentHunter/actions/runs/42177330555); staging Neon worker infrastructure was previously verified. Production still uses the legacy SQLite path; backup/restore evidence remains outstanding | Partial |
| 3 – Canonical identity | Deterministic normalization; variant distinctions; GTIN and canonical-key rules; durable ambiguity review; repeatable backfill | Identity, normalization, review queue and matching suites passed in integrated PostgreSQL/Redis run [42177330555](https://github.com/dalexmon81/ScentHunter/actions/runs/42177330555). Real-catalog precision/recall thresholds remain unmeasured | Partial |
| 4 – Universal connectors | Common contract; structured/API/feed preference; fixtures and contract tests per connector; rate/error handling; retailer authorization | Connector contracts and offline fixtures passed integrated CI [42177330555](https://github.com/dalexmon81/ScentHunter/actions/runs/42177330555). Live feed authorization and retailer terms remain unresolved; no live retailer is activated | Partial |
| 5 – Ingestion pipeline | Scheduled discovery/refresh; separate match and promotion gates; idempotency; retry/backoff; raw evidence; DLQ and quarantine recovery | Worker, Celery/Redis, matching, promotion and dead-letter suites passed integrated CI [42177330555](https://github.com/dalexmon81/ScentHunter/actions/runs/42177330555); prior staging worker ping/queued-task smoke passed. Real retailer refresh and recovery under live data remain unverified | Partial |
| 6 – Matching & validation | GTIN/SKU/deterministic matching; confidence thresholds; unresolved review; strict publication validation; audit trail | Matching, connector ingestion and fixture vertical slice passed integrated CI [42177330555](https://github.com/dalexmon81/ScentHunter/actions/runs/42177330555). Production precision/recall and human review operations still require evidence | Partial |
| 7 – Catalog-first search | Search reads only PostgreSQL canonical catalog and published offers; no retailer network calls in request path; real API response contract | PostgreSQL catalog search API and ingestion-to-search fixture vertical slice passed [42177330555](https://github.com/dalexmon81/ScentHunter/actions/runs/42177330555). Frontend bridge remains opt-in/default off; populated staging API/frontend integration remains unverified | Partial |
| 8 – Offer ranking & price history | Explainable ranking uses comparable currency, availability, freshness, store reliability, match confidence and shipping transparency; price history and trend tests | Ranking is integrated into PostgreSQL search, with ranking/API CI passing on [42177603832](https://github.com/dalexmon81/ScentHunter/actions/runs/42177603832); broader ranking and catalog acceptance also passed in [42176552789](https://github.com/dalexmon81/ScentHunter/actions/runs/42176552789). Frontend explanation and user-facing review remain | Partial |
| 9 – API & frontend | Real frontend uses PostgreSQL API; filters and empty states; stable schemas; staging end-to-end test | API contract and catalog search endpoint are covered by passing PostgreSQL tests. The frontend still does not use the new catalog route by default, and staging frontend integration is not proven | Partial |
| 10 – Observability & quality | Operational metrics for offers, freshness, connector health, matching, DLQ and latency; alert tests; admin review workflows | Authenticated operations metrics, review queues and dead-letter visibility passed integrated CI in [42176552789](https://github.com/dalexmon81/ScentHunter/actions/runs/42176552789). Live staging population, alert delivery and operational runbooks remain unverified | Partial |
| 11 – Gradual migration | Old/new parallel comparison; measured quality/latency; staged traffic progression; rollback and recovery rehearsal | Canary/shadow comparison and safety tests passed the dedicated Phase 11 step in [42176552789](https://github.com/dalexmon81/ScentHunter/actions/runs/42176552789). CI evidence only: no shadow traffic, percentage rollout, populated staging comparison, or rollback rehearsal has been authorized or performed | Partial |

## Latest integrated CI evidence (2026-11-06)

- Integrated PostgreSQL 16/Redis gate passed migrations, canonical seed, identity, connector, worker, matching, vertical-slice and catalog search suites: [run 42177330555](https://github.com/dalexmon81/ScentHunter/actions/runs/42177330555).
- Integrated ranking and catalog search tests passed: [run 42177603832](https://github.com/dalexmon81/ScentHunter/actions/runs/42177603832).
- Authenticated catalog operations, review-queue and dead-letter tests, plus Phase 11 canary/shadow checks, passed in the PostgreSQL vertical-slice workflow: [run 42176552789](https://github.com/dalexmon81/ScentHunter/actions/runs/42176552789).
- These CI runs use disposable databases and fixtures. They do not constitute live retailer data or production/staging rollout evidence.

## Evidence already obtained

- The integrated PostgreSQL 16 + Redis gate passed on commit `10930dbee8d23cad5841524a8fe9f2da024cb794`: [GitHub Actions run #42177378817](https://github.com/dalexmon81/ScentHunter/actions/runs/42177378817). It ran migrations twice, seeded the canonical catalog, compiled the backend, and passed the selected database/identity/connector/matching/worker/API/price-freshness suite. This is a strong integrated technical gate, not full release acceptance.
- The protected catalog metrics test workflow passed: [GitHub Actions run #42177360409](https://github.com/dalexmon81/ScentHunter/actions/runs/42177360409). It covers the aggregate metrics service and fail-closed token behavior, not alerting or an operator UI.

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
