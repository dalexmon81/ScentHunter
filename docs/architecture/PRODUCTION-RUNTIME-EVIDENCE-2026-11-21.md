# ScentHunter 2.0 — production evidence snapshot

Date: 2026-11-21
Source: GitHub Actions run logs and tracked Fly configuration on main. This is not a direct query of Fly secrets, live VM filesystem, or database contents.

## Deployment evidence

Latest inspected production Fly Deploy:
- Workflow run: 44817200071
- Commit: cbd7caac5d20d8c701535d0ad9eca257b0ff44d1
- Result: success
- Deployment, SQLite canonical catalog initialization, public health/catalog API smoke checks and several production catalog checks passed.

Fly config:
- App: scenthunter
- Region: ams
- Volume mount: scenthunter_data -> /data
- Legacy storefront database path: /data/store_catalog.sqlite3
- Foreground refresh disabled.
- Docker CMD starts catalog_family_coverage, phase0_baseline_worker and legacy FastAPI main:app.
- The production Fly workflow runs Alembic and seed_catalog.py against the isolated Phase 2 SQLite canonical catalog unless explicitly skipped. It does not prove PostgreSQL is active.

## Notino import failure evidence

Workflow run 44817718283 failed at the remote production import step on 2026-11-20.

Captured preflight:
- integrity: ok
- active_product_urls: 73,323
- persisted_variants: 0
- feed_status: DISCOVERY_PARTIAL
- feed_age_seconds: 558,833.9 (approximately 6.47 days)
- deployed CJ search: ready

Failure diagnostics:
- SQLite writer coordination lock remained owned by the uvicorn process.
- Stack trace identifies thread sh-catalog-discovery inside catalog_engine.catalog_discovery_loop, _save_discovery, and catalog_writer_lock.
- The import's own SQLite open failed with database is locked (catalog writer coordination lock timed out).
- The import aborted before independent persisted-row verification and public search verification.

This confirms a legacy SQLite writer-contention failure mode in the production feed import path. It does not by itself prove the canonical Phase 2 database has the same lock or that PostgreSQL is configured.

## Bplatz worker evidence

Workflow run 44817717935:
- Initial read-only baseline completed.
- Waited approximately six hours (348+ polling intervals) for a normal Bplatz worker success.
- No verifiable normal worker success appeared before timeout.
- Run failed at NORMAL_HYDRATION=TIMEOUT.
- Evidence artifact: phase2-bplatz-natural-worker-evidence, artifact ID 14689350363.

## Current conclusions

1. Production deployment was healthy by the workflow smoke checks, but this is not proof that ingestion was healthy.
2. Notino production feed import is blocked by an observed SQLite writer lock in the legacy catalog path, with the discovery loop holding the writer coordination lock.
3. Bplatz normal hydration did not complete within the six-hour observation window.
4. The production system is not yet proven to be PostgreSQL-backed.
5. Do not attempt another broad Notino import, restart the app to clear the lock, or alter production DB settings as a workaround. First capture a read-only Fly status, machine/volume inventory, secret names only, and runtime DB-backend report; then plan the isolated migration.

## Next read-only operator collection

Run locally with Fly CLI authenticated:
- flyctl status --app scenthunter
- flyctl machines list --app scenthunter
- flyctl volumes list --app scenthunter
- flyctl secrets list --app scenthunter (share names only; never values)
- A read-only SSH probe that reports only DB backend names, file paths/existence, and SQLite integrity_check results. Do not print environment values, passwords, tokens, or database URLs.
