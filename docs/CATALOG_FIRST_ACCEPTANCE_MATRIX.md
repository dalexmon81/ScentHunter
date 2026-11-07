# Catalog-first acceptance matrix (Phases 0–12)

This matrix is deliberately evidence-based. A directory, endpoint, green isolated test, or fixture does not by itself mark a phase complete.

## Completion rule

A phase can be accepted only when all three are demonstrated on the same integrated release candidate:

1. **Implemented** — production code and configuration are present.
2. **Verified** — automated tests and the relevant integration/operational checks pass.
3. **Connected** — the feature is exercised through the real adjacent components, not only as an isolated unit.

The overall ScentHunter trial remains blocked until every phase below is accepted and the release candidate passes the authorized operational and migration checks. No live retailer access, staging deployment, feature-flag activation, or production rollout is authorized by this document.

| Phase | Acceptance evidence required | Current evidence / remaining blocker | Status |
|---|---|---|---|
| 0 – Preparation & safety | **Architecture gate:** supported-store inventory, baseline worker/CSV contract sourced from canonical PostgreSQL, deterministic CSV validator with tests, protected repository workflow and disposable PostgreSQL backup/restore CI. **Operational gate after Phases 0–11:** approved live sources, reviewed real offer baseline and persistent staging backup/restore | Architecture evidence: nine-store inventory and connector registry documented; Phase 0 baseline worker now exports from canonical PostgreSQL (`stores`, `offers`, `product_variants`, `fragrances`, `brands`) in read-only transactions, with SQLite fail-closed guard; implementation and regression workflow merged via [PR #381](https://github.com/dalexmon81/ScentHunter/pull/381), full PostgreSQL vertical-slice CI passed in [run 42218839137](https://github.com/dalexmon81/ScentHunter/actions/runs/42218839137); deterministic CSV validator and regression tests merged via [PR #378](https://github.com/dalexmon81/ScentHunter/pull/378); default-branch ruleset and disposable PostgreSQL backup/restore rehearsal passed in [run 42179338407](https://github.com/dalexmon81/ScentHunter/actions/runs/42179338407). Operational evidence is explicitly deferred until the integrated architecture is ready: no live retailer source accepted, no reviewed real offer baseline, and no persistent staging backup/restore rehearsal. | Partial |
| 1 – Repository cleanup | Clear module boundaries; legacy diagnostics outside production path; dependency/import checks; no accidental runtime coupling | PRs #383–#385 established diagnostic isolation and extracted catalog search service/repository. PR #387 extracted shared store identity normalization; PR #388 moved retailer execution configuration into `app.config.store_registry`; PR #389 extracted catalog readiness/coverage rules; PR #390 extracted legacy product-matcher bootstrap; PR #391 extracted safe numeric parsing. The full PostgreSQL vertical-slice workflow passed on PR #391 head in [run 42258206822](https://github.com/dalexmon81/ScentHunter/actions/runs/42258206822). These are verified increments, not phase acceptance: `backend/main.py` remains a large legacy composition module with operational resync, startup/lifespan, identity resolution, legacy catalog orchestration and diagnostic helpers still embedded. Remaining work includes extracting those responsibilities behind tested modules, removing obsolete inline diagnostics and proving import/startup isolation. | Partial |
| 2 – Database & data model | PostgreSQL migrations repeat safely; canonical schema and seed are idempotent; runtime rejects unintended SQLite in staging; backup/restore | The Fly staging API and Celery worker now share the guarded PostgreSQL catalog connection. The staging deployment workflow on PR #424 head `0347f8607ab0952dee37e425ac3b69dd9e7d471b` has passed deploy, public-IP allocation, one API/one worker/zero Beat topology, worker/broker startup, read-only database audit, Alembic migration, brand alias normalization and canonical seed steps; its fixture-backed CI separately passed PostgreSQL backup/restore. The normal legacy application path still uses SQLite, and a persistent staging backup/restore rehearsal remains outstanding. The final public DNS/HTTPS check in run [42339429160](https://github.com/dalexmon81/ScentHunter/actions/runs/42339429160) remains in progress and must not be treated as passed. | Partial |
| 3 – Canonical identity | Deterministic normalization; variant distinctions; GTIN and canonical-key rules; durable ambiguity review; repeatable backfill | Identity, normalization, review queue and matching suites passed in [integrated run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). Real-catalog precision/recall thresholds remain unmeasured | Partial |
| 4 – Universal connectors | Common contract; structured/API/feed preference; fixtures and contract tests per connector; rate/error handling; retailer authorization | Connector contracts and offline fixtures passed in [integrated run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). No source is currently proven authorized for live ingestion: Bplatz permission is pending, Notino.fr CJ approval/feed entitlement is pending, and Deloox has a prior HTTP 403. Store coverage and permitted access remain unresolved | Partial |
| 5 – Ingestion pipeline | Scheduled discovery/refresh; separate match and promotion gates; idempotency; retry/backoff; raw evidence; DLQ and quarantine recovery | The isolated staging worker is deployed with exactly one non-root worker and zero Beat machines. In PR #424 deploy run [42339429160](https://github.com/dalexmon81/ScentHunter/actions/runs/42339429160), the one-API/one-worker/zero-Beat check, broker ping and queued smoke task all passed. The catalog seed deliberately does not activate a retailer. Staging still has no authorized live source and zero offers to ingest, so real retailer discovery, normalization, matching, publication, refresh and recovery remain unproven. | Partial |
| 6 – Matching & validation | GTIN/SKU/deterministic matching; confidence thresholds; unresolved review; strict publication validation; audit trail | Matching, validation, review queue and fixture vertical slice passed in [integrated run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). Real-catalog precision/recall and human review operations remain unmeasured | Partial |
| 7 – Catalog-first search | Search reads only PostgreSQL canonical catalog and published offers; no retailer network calls in request path; real API response contract | PR #424 adds a separate catalog-first FastAPI entrypoint that serves the existing frontend and reads PostgreSQL only. The Fly staging smoke test in run [42339429160](https://github.com/dalexmon81/ScentHunter/actions/runs/42339429160) passed for `/healthz`, frontend and `/search-start?q=Sauvage`; it found Dior Sauvage and returned four product identities, with zero offers as the seed intentionally leaves retailers inactive. No retailer requests run in the user-search path. Populated real-offer search remains outstanding; the same run's final public HTTPS check is still in progress. | Partial |
| 8 – Offer ranking & price history | Explainable ranking uses comparable currency, availability, freshness, store reliability, match confidence and shipping transparency; price history and trend tests | Ranking is integrated into PostgreSQL search and the frontend display; ranking/API and broader vertical-slice tests passed in [run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). Real populated-catalog and staging validation remain | Partial |
| 9 – API & frontend | Real frontend uses PostgreSQL API; filters and empty states; stable schemas; staging end-to-end test | The existing frontend is served by the isolated staging API at [scenthunter-staging-workers.fly.dev](https://scenthunter-staging-workers.fly.dev/). Fly's internal staging smoke checks verified `/healthz`, `/` and a completed PostgreSQL search for Dior Sauvage (four product identities, zero offers) in run [42339429160](https://github.com/dalexmon81/ScentHunter/actions/runs/42339429160). The final public DNS/HTTPS check has not yet concluded. Full filters, mobile acceptance and real published-offer display remain outstanding. | Partial |
| 10 – Observability & quality | Operational metrics for offers, freshness, connector health, matching, DLQ and latency; alert tests; admin review workflows | Authenticated metrics, identity/match review queues and dead-letter visibility passed in [run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). Live staging population, alert delivery, operator-runbook execution, quarantine recovery and staging/production restore evidence remain | Partial |
| 11 – Gradual migration | Old/new parallel comparison; measured quality/latency; staged traffic progression; rollback and recovery rehearsal | Stable cohorts, explicit percentage gating, background non-serving shadow reads and comparison tests passed in [run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413). No real shadow traffic, canary percentage, populated staging comparison or rollback rehearsal has been authorized/performed | Partial |
| 12 – Scaling & new markets | Retailer isolation; explicit source authorization; market-aware country/currency/shipping policy; shared freshness/publication gates; bounded worker capacity; per-market observability; contract, isolation, idempotency, security and load tests | Architecture acceptance rules are specified in [Phase 12 scaling acceptance](PHASE_12_SCALING_ACCEPTANCE.md). A shared supported-currency policy now allows EUR only and blocks unsupported codes at canonical publication and the isolated next-engine offer model; full CI verification is pending in PR #393. This does not enable non-EUR markets or FX conversion. Representative multi-market data, measured load/backpressure, real-source authorization and operational recovery evidence remain outstanding. | Partial |

## Latest PR #424 staging evidence (2026-11-07)

- PR #424 head is `0347f8607ab0952dee37e425ac3b69dd9e7d471b` and remains open/draft. No merge or production operation was performed.
- The Catalog-first API contract workflow passed: [run 42339431429](https://github.com/dalexmon81/ScentHunter/actions/runs/42339431429).
- The PostgreSQL vertical-slice workflow passed: [run 42339429199](https://github.com/dalexmon81/ScentHunter/actions/runs/42339429199). It covers disposable migrations and seed, disposable backup/restore, connector contracts, worker ingestion/matching/promotion, a fixture-backed end-to-end path through the catalog API, fail-closed search, admin metrics/queues, canary/shadow checks and the live-retailer-credential boundary. It remains fixture-based CI, not live retail data.
- The Fly staging deploy run [42339429160](https://github.com/dalexmon81/ScentHunter/actions/runs/42339429160) passed the Fly image deploy, public IP allocation, one API/one non-root worker/zero Beat machine checks, broker startup, schema audit, Alembic migration, brand normalization, canonical seed without activating a store, Celery ping, queued task execution and internal frontend/PostgreSQL search smoke test.
- The public DNS/HTTPS test in that same deploy run is still in progress. The run is not accepted as fully successful until that step and final worker/machine inspection finish.
- The staging seed intentionally leaves `stores=0` and `offers=0`. No retailer credentials are configured or authorized by these checks. No real prices or active offers exist yet; user-facing comparison of live prices remains blocked on an approved source.
- PR #424 also contains the promotion session-factory fix (ported from the separate #422 branch), the Fly config with only `app` and `web` processes, and the corrected staging scale command that no longer references the removed Beat process group.

## Latest integrated acceptance evidence (2026-11-06)

- The same integrated workflow now includes a guarded `pg_dump`/`pg_restore` rehearsal. It creates and removes only a `ci_restore_*` database on loopback PostgreSQL, compares catalog row counts and Alembic revision, and passed as part of [run 42179338407](https://github.com/dalexmon81/ScentHunter/actions/runs/42179338407). This does not back up or restore staging/production.


- The combined PostgreSQL 16/Redis workflow passed migrations, seed, schema, identity, connectors, ingestion, matching, vertical slice, catalog search API, admin metrics/review/dead-letter routes, rollout/shadow tests, frontend cohort-header check, and the offline retailer-credential boundary: [run 42178701413](https://github.com/dalexmon81/ScentHunter/actions/runs/42178701413).
- Subsequent behavior-preserving Phase 1 extractions were merged in PRs #387–#391. The complete PostgreSQL 16/Redis vertical-slice workflow passed on PR #391 head in [run 42258206822](https://github.com/dalexmon81/ScentHunter/actions/runs/42258206822), including migrations, disposable backup/restore, connector and worker suites, fixture-backed ingestion/promotion, catalog search/fail-closed tests, admin routes, canary/shadow routing, frontend cohort key and credential-boundary checks. This verifies the integrated CI path, not the remaining modularization or live operations.
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
- The search-path safety correction disables foreground retailer refresh/live fallback and returns an explicit error when the legacy catalog engine is unavailable. The full `/search-start` route regression is now covered in `backend/tests/test_catalog_search_fail_closed.py` (commit `f208c207dc8246187d10e5557ca9888fa798aa9d`), and that test file is included in the vertical-slice workflow (workflow-path update `f955a021390a6ece120751f1f8e02bdbb642d5c4`). As of the latest audit, GitHub reports no PR-triggered workflow run and no commit status checks for `f955a02`; this regression is therefore committed but not CI-verified.
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


### Ingestion concurrency and publication-policy follow-up (2026-11-06)

- Added a partial unique index on `(store_id, external_product_id)` for live raw-ingestion states (`pending`, `unmatched`, `matched`). Promoted/rejected evidence remains historical and is not blocked by this guard.
- The staging path now catches the concurrent-insert uniqueness race, reloads the winning live row and merges the new observation into its bounded refresh history instead of creating a duplicate or failing the connector batch.
- Discovery completion is tied to the exact `IngestionRun.id` created by that task. Validation also compares payload store identity to the owning database store.
- Publication policy is intentionally conservative: `unknown` stock is retained as evidence for review; `preorder` is retained but not published until the publication contract and downstream search/UI explicitly support it. Only `in_stock` and `out_of_stock` currently pass promotion.
- Migration `0009_live_ingestion_uniqueness` adds the database-level concurrency guard. It has not been applied to staging or production. Existing duplicate live rows, if any, must be reconciled before that migration can safely be applied to a persistent database.
- The separate `run_connector_once` worker still stages through an alternate path and is not yet proven to share the same normalize/validate/match/promote lifecycle. This remains open work; no phase acceptance is implied.


### Source timestamp and freshness follow-up (2026-11-06)

- Offer promotion now parses the retailer-provided `capturedAt` value and persists that observation time to both `offers.captured_at` and `price_history.captured_at`. Existing records without a source timestamp continue to use the promotion-time UTC timestamp.
- An explicitly supplied malformed or timezone-naive `capturedAt` is blocked from publication instead of being silently replaced with the worker clock.
- Regression coverage verifies timestamp preservation on first publication and rejection of malformed source timestamps. The PostgreSQL vertical-slice workflow passed on commit `dbb1a215ebcf0953ad59fcd4308fbadcd252e3ff` (run [42191109827](https://github.com/dalexmon81/ScentHunter/actions/runs/42191109827)).
- At the time of this audit, offer expiry was unresolved. The later “Explicit offer freshness policy” section below supersedes that finding with a store-configured TTL and fail-closed search/publication gate.
- The legacy `run_connector_once` helper remains an alternate staging-only implementation; it is not yet unified with the Celery normalize/validate/match/promote pipeline. This remains open work.
- The successful CI run uses disposable PostgreSQL/Redis services and offline fixtures only. It does not prove persistent staging/production restore, live retailer coverage, or readiness to enable traffic.


### Explicit offer freshness policy (2026-11-06)

- Added nullable `stores.offer_ttl_minutes` with a positive-value database constraint and Alembic revision `0010_store_offer_ttl`.
- Publication now requires a configured positive TTL for the owning active store. The expiry is calculated from the source observation timestamp (`captured_at + store.offer_ttl_minutes`) and persisted to `offers.valid_until`. Repeat hydration refreshes both the observation timestamp and expiry.
- Catalog search now returns only active offers with a non-null, unexpired `valid_until`. Legacy rows without an expiry are hidden rather than treated as valid indefinitely.
- No production retailer TTL has been guessed or automatically seeded. The Bplatz TTL used in PostgreSQL integration tests is test-only; real store TTLs remain operator configuration and must be based on observed source update cadence and acceptable staleness.
- The synchronous `run_connector_once` helper is a legacy compatibility/fixture adapter, not a production worker. A regression test now asserts that the Celery worker imports and routes only `app.workers.ingestion_tasks`; the compatibility module is not part of the production worker topology. The adapter uses the shared payload validation contract. Production discovery remains `ingestion_tasks.discover_store_products`, which queues normalization, validation, matching and promotion.
- The migration and new fail-closed publication/search behavior still require a successful full CI run on the current branch head before acceptance. No persistent database has been migrated.


- Freshness-policy verification passed in the complete PostgreSQL vertical-slice CI run on commit `4468fd27b2e62de33b2d41629ec453316e912fba` ([run 42193706637](https://github.com/dalexmon81/ScentHunter/actions/runs/42193706637)). This includes schema migration, disposable PostgreSQL backup/restore, connector/worker tests, fixture-backed ingestion-to-promotion, catalog search/fail-closed tests, authenticated admin metrics and canary/shadow routing checks.
- The authenticated admin API now supports `PUT /catalog/admin/stores/{store_slug}/freshness-policy?offer_ttl_minutes={positive_integer}`. Updating a store policy recomputes expiry for its existing active offers from their original `captured_at` timestamps. Metrics separately report active publishable offers, stale offers, missing expiries and active stores without a TTL.
- This CI run is disposable/offline evidence only. It does not authorize applying revision `0010_store_offer_ttl` to a persistent database, assigning real retailer TTL values, activating stores, enabling canary traffic or declaring Phases 0–10 complete.


- Follow-up implementation: `promote_offer` now rejects publication when the active store has no positive `offer_ttl_minutes` configured, and computes `valid_until` from the preserved source observation timestamp. Repeat publication refreshes the expiry using the new source timestamp.
- Regression tests cover missing-TTL rejection, initial expiry calculation, and expiry refresh on repeat hydration. The Notino PostgreSQL vertical-slice fixture now explicitly configures its test-only TTL even when the store row already exists.
- CI for these latest changes is running; do not mark this follow-up accepted until the full run completes successfully. Store TTL values for real retailers remain unconfigured until their freshness cadence is verified.


- The latest full PostgreSQL vertical-slice run passed on commit `390d43598ac3fe4720bba2cce62f55bd5748194f` ([run 42194181552](https://github.com/dalexmon81/ScentHunter/actions/runs/42194181552)). It includes the TTL publication gate and expiry tests, the Notino fixture with explicit test TTL, and the guard that excludes the synchronous compatibility adapter from production Celery worker imports/routes.
- The passing run still uses disposable PostgreSQL/Redis and offline fixtures. It does not prove persistent-environment restore, live retailer authorization/coverage, or production readiness. Real retailer TTLs remain deliberately unset until evidence supports each value.


### Normalization review and current integrated CI follow-up (2026-11-06)

- Conflicting or invalid product attributes that raise during normalization are now retained as explicit review work instead of failing the worker task and relying on retries/dead-letter handling. The raw record remains unmatched with `match_method=normalization_review`, a bounded rejection reason, and a persisted `_normalization.status=review_required` payload marker.
- The authenticated `GET /catalog/admin/review-queue` response now includes a `normalization_reviews` collection with store, external product identifier, reason, raw evidence and creation time. Admin metrics tests also seed and assert this queue.
- Regression coverage verifies that a conflicting EDP/EDT payload is recorded for review without worker failure. A JSON persistence issue in the first implementation was fixed by assigning a new payload object rather than mutating the existing JSON dictionary in place.
- The full PostgreSQL vertical-slice workflow passed on head commit `a214d6dadc9eafcaa57ceceb7b63ea98dc4729a0`: [run 42197618443](https://github.com/dalexmon81/ScentHunter/actions/runs/42197618443). The passing run includes migrations and seed, disposable PostgreSQL backup/restore, worker and matching suites, fixture-backed ingestion-to-promotion, PostgreSQL search/fail-closed tests, admin metrics/review queues, canary/shadow checks, frontend cohort key, and the retailer-credential boundary.
- This passing CI supersedes earlier statements in this matrix that the fail-closed search correction or the normalization-review test were still pending CI. It does not supersede the operational blockers above: no persistent staging/production migration or restore, live retailer coverage, populated staging offer catalog, alert/recovery exercise, real shadow comparison or traffic rollout has been performed.
- Matching remains deliberately exact-only (verified GTIN or exact canonical key). SKU mappings, broader deterministic alias coverage, fuzzy/semantic candidate generation and measured real-catalog precision/recall remain open; uncertain matches must continue to stay in review rather than being auto-published.
- No phase is marked complete by this follow-up. PR #374 remains open/draft; no merge, deploy, persistent DB operation, retailer request, store activation or traffic change was performed.


### PostgreSQL catalog search indexing follow-up (2026-11-06)

- Added Alembic revision `0011_catalog_search_fts` with PostgreSQL GIN indexes over `to_tsvector('simple', brands.name)` and `to_tsvector('simple', fragrances.name)`. Non-PostgreSQL dialects skip index creation; SQLite test compatibility remains.
- The PostgreSQL catalog search path now tokenizes the query and requires each token to match either the brand or fragrance name using PostgreSQL full-text search. This permits cross-field queries such as `Dior Sauvage` while preventing a query with an unmatched token from returning a partial-name result. SQLite fixtures retain the prior ILIKE fallback.
- Added regression coverage for multi-token cross-field matching and a non-matching extra token. The read-only Bplatz schema preflight allow-list includes revision `0011_catalog_search_fts`.
- Full PostgreSQL vertical-slice CI passed on head commit `31f19910ef785c5303711711dbfe34ed2ea23f5d`: [run 42200323517](https://github.com/dalexmon81/ScentHunter/actions/runs/42200323517). The run includes schema migrations, PostgreSQL backup/restore rehearsal on disposable CI database, ingestion/matching/promotion, catalog search and fail-closed tests, admin metrics, rollout routing and frontend cohort checks.
- This is indexed token search, not typo-tolerant or semantic search. It does not yet search concentration, size, packaging, olfactory family or notes as query dimensions. Ranking and matching precision still require representative catalog evaluation. No persistent database migration, staging audit, retailer access, merge, deploy or traffic change was performed.
