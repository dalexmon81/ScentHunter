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
- Celery task definitions, queue routing, handler registration, and Redis configuration exist in `backend/app/workers/`.
- The worker README explicitly gates a multi-machine Celery deployment on shared PostgreSQL, a dedicated Redis broker, a separate worker deployment, and runtime verification.

**Not proven:** a live Celery worker is deployed and consuming tasks against the same shared PostgreSQL catalog used by the API.

## Deployment workflow blocker — do not dispatch

The current `.github/workflows/deploy-staging-worker.yml` is not aligned with the checked-in `main` deployment files:

1. It checks out branch `phase5/fly-staging-workers-config`. That ref currently returns “No commit found”.
2. It invokes `fly.staging-workers.toml`, which is not present on `main` and cannot be fetched from that missing ref.
3. It expects Alembic revision `0007_ingestion_dead_letters` and tables such as `ingestion_artifacts` and `ingestion_dead_letters`; current `main` contains migrations only through `0005_connector_quarantine`.
4. It targets Fly app `scenthunter-staging-workers`, while the checked-in `fly.staging.toml` targets `scenthunter-pilot-20261030` and the SQLite pilot image.

This workflow must be reconciled with the current source, migrations, app identity, and worker image before anyone dispatches it. Do not use it as evidence that staging is ready. No deploy, secret change, resource provisioning, or database migration is authorized by this documentation update.

## Notino CJ feed publication

PR [#806](https://github.com/dalexmon81/ScentHunter/pull/806) contains a narrow staging-index optimization for the slow URL-grouping phase of the Notino feed publisher. Its parser and regression checks have passed in the PR checks inspected on 2026-11-20. The live feed parsing jobs in the latest inspected run were skipped.

The PR remains open and unmerged. Its final operational gate remains a separately authorized full-feed import, followed by checks of published variants, URLs, stock, currency provenance, and catalog search visibility. Raw feed rows, parsed offers, matched variants, and published offers must be reported separately.

## Production readiness gaps

1. Reconcile or replace the stale staging-worker deployment workflow and create a single source of truth for app, image, database, queue, and migration-head configuration.
2. Provision an isolated PostgreSQL target and dedicated Redis broker only after the deployment configuration is reviewed.
3. Deploy one separate Celery worker against the same PostgreSQL catalog as the API; verify broker ping, task execution, durable ingestion-run lifecycle, retry/recovery, and shutdown.
4. Run a bounded Notino discovery/fetch pilot with explicit operator approval. Verify evidence and counts at every stage before publishing.
5. Rehearse PostgreSQL backup and restore, then test migration rollback/recovery on disposable infrastructure.
6. Verify the deployed frontend commit and API/database identity. Run shadow/canary traffic and prove rollback before any production cutover.
7. Expand retailer coverage one store at a time with explicit provisioning and approved discovery seeds.

## Safety invariants

- Do not delete `product_catalog.json`, `family_registry.json`, legacy scrapers, or the legacy runtime as part of this work.
- Do not perform broad retailer scraping inside a user search request.
- Do not publish guessed identity, stock, URL, price, or currency.
- Do not launch the stale staging workflow or migrate a production database until the deployment mismatch and recovery gates are resolved.
- Do not claim production readiness from unit tests, a successful build, or a CI-only PostgreSQL service.
