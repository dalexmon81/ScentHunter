# Fly.io Phase 5 staging workers

Separate from the production `fly.toml`.

- Fly app: `scenthunter-staging-workers`
- Config: `fly.staging-workers.toml`
- Region: Amsterdam (`ams`)
- One Celery worker machine; optional Beat process group scaled to zero.
- No HTTP service, public port, production volume, or production app name.

Required Fly secrets:
- `SCENTHUNTER_CATALOG_DATABASE_URL`: dedicated staging PostgreSQL URL.
- `SCENTHUNTER_REDIS_URL`: dedicated staging Redis TLS TCP URL.

Optional Notino CJ/VIV secrets:
- `NOTINO_CJ_FEED_URL`
- `NOTINO_CJ_FEED_USERNAME`
- `NOTINO_CJ_FEED_PASSWORD`

The workflow reports only whether Notino secrets are present. It never prints values or calls the feed. Do not use production database credentials, production volumes, or Redis REST credentials.

The workflow scales to one worker and zero Beat machines, verifies the staging database identity, applies Alembic migrations, and seeds canonical identities without retailer opt-in flags. The seed must create no store rows and no offers. Bplatz activation is a separate explicit opt-in for its integration test.

Do not activate Notino or run the feed preflight until the catalog seed, matching identity, and staging store configuration have been reviewed. Scheduled discovery and retailer refresh remain disabled.
