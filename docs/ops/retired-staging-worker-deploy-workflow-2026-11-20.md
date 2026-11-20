# Retired staging worker deployment workflow

Date: 2026-11-20

## Decision

The workflow `.github/workflows/deploy-staging-worker.yml` has been retired. It must not be dispatched or copied into a new deployment path.

## Why it was unsafe to keep

The workflow was not aligned with the checked-in `main` branch:

- It checked out `phase5/fly-staging-workers-config`, a ref that no longer exists.
- It referenced `fly.staging-workers.toml`, which is not present on `main`.
- It expected Alembic revision `0007_ingestion_dead_letters`, while the current canonical database migration head on `main` is `0005_connector_quarantine`.
- It targeted Fly app `scenthunter-staging-workers`, while the checked-in pilot configuration targets the isolated `scenthunter-pilot-20261030` app and SQLite volume.
- It performed remote secret deployment, Fly deployment, migrations, alias updates and catalog seeding. Those actions could not be safely inferred from the current repository configuration.

The workflow was therefore not merely an outdated convenience file. It encoded a different deployment topology and database contract.

## What remains supported

The isolated pilot configuration remains in `fly.staging.toml` and uses `Dockerfile.pilot` with a persistent SQLite volume and the single-machine SQLite queue.

The pilot is not equivalent to a multi-machine staging worker or production deployment. Do not attach another worker to its machine-local SQLite database.

## Requirements before introducing a replacement

A new staging deployment workflow must be reviewed against the actual checked-in code and infrastructure and must:

1. Use an existing, reviewed Fly app and a configuration committed to the same branch.
2. Use the current Alembic head and verify the target database identity before migrations.
3. Use shared PostgreSQL for API and worker processes; never attach separate machines to independent SQLite files.
4. Provision a dedicated Redis broker and scope credentials to the intended non-production app.
5. Deploy the worker as a separate process with an explicit process group and non-root runtime.
6. Verify worker ping and task execution using a task that actually exists in the checked-in runtime.
7. Include backup/restore, canary, rollback and post-deploy health checks.
8. Keep retailer feed imports and store activation as separate, explicit operator actions.

## Scope

This retirement removes only the stale GitHub Actions workflow. It does not delete Fly apps, volumes, databases, secrets or any running service. It does not perform a deployment, migration, secret change or feed import.
