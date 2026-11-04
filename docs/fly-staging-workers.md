# Fly.io Phase 5 staging workers

This configuration is deliberately separate from the production `fly.toml`.

## Isolation

- Fly app: `scenthunter-staging-workers`
- Config: `fly.staging-workers.toml`
- Image: `backend/Dockerfile.worker`
- Region: Frankfurt (`fra`)
- Process groups: one Celery worker and one Celery Beat scheduler
- No HTTP service, public port, production volume, or production app name

## Required runtime secrets

Set these only after confirming that both services point to staging resources:

- `SCENTHUNTER_CATALOG_DATABASE_URL`: the connection URL for the dedicated staging PostgreSQL database. Never use the production Fly volume or production database URL.
- `SCENTHUNTER_REDIS_URL`: the private Redis connection URL for the dedicated staging Upstash database. Use the TLS TCP URL, not the REST URL or REST token.

Optional settings can be added later after reviewing their values:

- `SCENTHUNTER_DISCOVERY_TERMS_JSON`
- `SCENTHUNTER_CONNECTOR_QUARANTINE_AFTER` (defaults to 3)

Do not commit credentials to GitHub or put them in this file. Configure them as Fly secrets.

## Deployment gate

Do not deploy until all of the following are true:

1. The staging Neon PostgreSQL project/database is confirmed separate from production.
2. The staging Redis database is confirmed separate from production and its TLS TCP URL is available.
3. Both required secrets are set on `scenthunter-staging-workers`.
4. Alembic migrations and the Phase 2 seed have been run against staging only.
5. The Fly launch configuration points to this file, this branch, and `backend/Dockerfile.worker`.

Deploy from the repository root using the explicit config file `fly.staging-workers.toml`. Never use the default `fly.toml` for this worker app.

The first staging run must be monitored. Do not activate retailer discovery or live retailer refresh until the staging database has been reviewed and store activation has been explicitly approved.
