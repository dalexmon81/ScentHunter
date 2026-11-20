# ScentHunter catalog-first status — verified 2026-11-20

## Executive status

The catalog-first application path is present on `main`. This is not yet a production cutover of the ingestion architecture. The remaining work is operational integration and proof: PostgreSQL target, separately deployed Celery worker and Redis, verified data migration, production backup/restore, and a controlled rollout.

This document supersedes the older status statements that described catalog search as opt-in and the frontend default as legacy. Those statements no longer match `main`.

## Verified on `main`

### Catalog database and migrations

- `backend/app/db.py` supports SQLite and PostgreSQL through SQLAlchemy and psycopg 3.
- SQLite remains the default unless an explicit database URL is configured. `SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL` can make a PostgreSQL URL mandatory.
- Alembic migrations currently present on `main` are `0001` through `0005_connector_quarantine`; the current checked-in head is `0005_connector_quarantine`.
- `.github/workflows/phase2-postgresql.yml` defines a disposable PostgreSQL 16 CI service, repeatable Alembic upgrade, complete checked-in catalog seed/import, checksums, idempotent repeat import, schema/constraint tests, and catalog search regressions.
- `backend/scripts/migrate_canonical_sqlite_to_postgres.py` is dry-run-first, opens the SQLite source read-only, requires an explicit PostgreSQL migration target, checks the schema/revision, and supports an explicitly confirmed apply.

**Not proven by these code checks:** a production PostgreSQL database has been provisioned, populated, backed up, or restored successfully. Do not point the importer at production without a separate approved runbook and restore rehearsal.

### Frontend and search

- `frontend/index.html` uses `/api/catalog/search` by default.
- The old `/search-start` retailer-search path is retained only as an explicit diagnostic opt-out with `?catalog_first=0`.
- `backend/app/api/catalog_search.py` exposes catalog search and status endpoints.
- `backend/app/search/catalog.py` documents and implements a database-only search: it does not contact retailers or mutate catalog data during a user search.
- Offer publication filters include active store/offer state, promoted raw evidence, matching audit, in-stock state, positive price, explicit EUR provenance, valid retailer-domain URL, and a 24-hour freshness window.

The canonical frontend path is therefore already the default in the current source. This does not by itself prove that the production deployment is serving the same commit or that its database contains enough valid offers.

### Worker architecture

- The single-machine pilot uses a durable SQLite queue and `backend/app/workers/sqlite_worker.py`.
- `Dockerfile.pilot` starts that SQLite worker alongside the API in the pilot machine.
- `fly.staging.toml` targets the isolated app `scenthunter-pilot-20261030`, uses a persistent SQLite volume, and selects the SQLite queue backend.
- Celery task definitions, queue routing, and Redis configuration exist in `backend/app/workers/`.
- The registered runtime handlers on `main` currently cover `discover`, `fetch`, and `refresh` (Notino plus the four legacy scraper adapters).
- Celery tasks and queue routes also exist for `normalize`, `match`, `validate`, `quarantine`, and `reprocess`, but those stages do not have runtime handlers registered. A direct task execution for one of those stages fails closed with `HandlerNotConfigured`.
- In the current retailer path, parsing, normalization, canonical matching, validation, and offer promotion are performed together inside `persist_connector_record` during the fetch handler. They are not yet independent queue workers. Connector quarantine is recorded directly by the discovery/fetch/refresh handlers through `record_connector_failure`; it is not a separate dead-letter queue consumer.
- PR #808 adds a CI-only Redis-backed worker smoke test. The worker successfully answered a broker ping and executed a no-side-effect probe task. This proves broker-to-worker task execution in CI, not deployment to Fly or use of a shared staging database.
- The worker README gates multi-machine deployment on shared PostgreSQL, dedicated Redis, a separate worker deployment, and runtime verification.

**Not proven:** a live Celery worker is deployed and consuming tasks against the same shared PostgreSQL catalog used by the API. The five downstream queue stages listed above are not operationally wired as separate handlers.

## Deployment workflow retirement — pending review

On the `main` baseline inspected for this document, `.github/workflows/deploy-staging-worker.yml` was misaligned with the checked-in deployment files: it referenced a missing branch (`phase5/fly-staging-workers-config`), a missing `fly.staging-workers.toml`, Alembic revision `0007_ingestion_dead_letters` (while `main` was at `0005_connector_quarantine`), and Fly app `scenthunter-staging-workers` rather than the SQLite pilot app.

PR [#811](https://github.com/dalexmon81/ScentHunter/pull/811) proposes removing that stale deployment workflow and recording the retirement rationale. It remains a proposed change until merged. Do not dispatch the old workflow. The separate `phase5-readonly-staging-audit.yml` is read-only and is not the deploy workflow. No Fly app, volume, database, or secret is deleted or changed by PR #811.

## Proposed code and test changes under review

The following are separate open pull requests and are not part of `main` until merged:

- PR [#809](https://github.com/dalexmon81/ScentHunter/pull/809) aligns the Celery queue contracts with the currently registered `discover`, `fetch`, and `refresh` runtime stages, removing misleading downstream task contracts that have no handlers. It does not add independent downstream workers or change catalog data.
- PR [#808](https://github.com/dalexmon81/ScentHunter/pull/808) adds a CI-only Redis-backed Celery worker smoke test. A real worker answered `ping` and executed a no-side-effect probe in GitHub Actions; this is not a Fly deployment.
- PR [#810](https://github.com/dalexmon81/ScentHunter/pull/810) adds the canonical Dior Sauvage EDP 100 ml variant with validated GTIN `3348901368247`, plus a temporary-SQLite integration test covering seed, exact GTIN match, Notino-shaped connector parsing, offer promotion, catalog search before/after ingestion, and seed idempotency. The simulated €89.90 offer exists only in the disposable test database, not in the checked-in catalog.
- PR [#811](https://github.com/dalexmon81/ScentHunter/pull/811) retires the misaligned staging deploy workflow as described above.

These PRs were reported with passing required CI checks at the time of review, but they remain unmerged and must be rechecked before merge.

## Notino CJ feed publication

PR [#806](https://github.com/dalexmon81/ScentHunter/pull/806) contains a narrow staging-index optimization for the slow URL-grouping phase of the Notino feed publisher. Its parser and regression checks have passed in the PR checks inspected on 2026-11-20. The live feed parsing jobs in the latest inspected run were skipped.

The PR remains open and unmerged. Its final operational gate remains a separately authorized full-feed import, followed by checks of published variants, URLs, stock, currency provenance, and catalog search visibility. Raw feed rows, parsed offers, matched variants, and published offers must be reported separately.

A separate read-only public-storefront smoke run on 2026-11-20 completed without touching the database or using the CJ feed. It found priced Notino.fr product pages for 2 of 5 test queries. Both Dior Sauvage results (100 ml at €136.00 and 200 ml at €69.70) had `availability=unknown`; they are discovery candidates, not publishable offers. The smoke script currently labels normalized priced rows as `verified_offers`, so that counter must not be interpreted as stock verification or successful catalog publication. The direct Notino search endpoints returned HTTP 403 and the fallback reader supplied the candidates. This test does not verify the authorized CJ feed, GTIN matching against live feed rows, or live stock.

## Production readiness gaps

1. Decide whether to retain the existing atomic fetch pipeline or implement independently queued normalization/matching/validation stages. PR #809 proposes removing currently unused downstream queue contracts; review and merge it before treating that cleanup as part of `main`.
2. Retire the stale staging-worker deploy workflow and establish one source of truth for app, image, database, queue, and migration-head configuration. PR #811 proposes the workflow retirement; it does not provision or deploy a replacement.
3. Provision an isolated PostgreSQL target and dedicated Redis broker only after the deployment configuration is reviewed.
4. Deploy one separate Celery worker against the same PostgreSQL catalog as the API; verify broker ping, task execution, durable ingestion-run lifecycle, retry/recovery, and shutdown.
5. Run a bounded Notino discovery/fetch pilot with explicit operator approval. Verify evidence and counts at every stage before publishing.
6. Rehearse PostgreSQL backup and restore, then test migration rollback/recovery on disposable infrastructure.
7. Verify the deployed frontend commit and API/database identity. Run shadow/canary traffic and prove rollback before any production cutover.
8. Expand retailer coverage one store at a time with explicit provisioning and approved discovery seeds.

## Safety invariants

- Do not delete `product_catalog.json`, `family_registry.json`, legacy scrapers, or the legacy runtime as part of this work.
- Do not perform broad retailer scraping inside a user search request.
- Do not publish guessed identity, stock, URL, price, or currency.
- Do not launch the stale staging workflow or migrate a production database until the deployment mismatch and recovery gates are resolved.
- Do not claim production readiness from unit tests, a successful build, or a CI-only PostgreSQL service.
