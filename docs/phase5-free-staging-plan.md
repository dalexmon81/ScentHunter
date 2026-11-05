# Phase 5 — zero-cost staging plan

## Goal

Validate the Phase 5 Redis/Celery ingestion runtime without changing the production
Fly.io app `scenthunter`, without merging PR #343, and without authorizing new
paid resources.

## Current verified state

- PR #343 (`phase5/redis-celery-ingestion-pipeline`) contains the Celery worker,
  six queues, Beat schedule, additive Alembic migrations, and a disposable
  PostgreSQL + Redis integration job in GitHub Actions.
- The GitHub Actions integration job starts PostgreSQL 16 and Redis 7.4 as
  temporary service containers, applies migrations, seeds the canonical
  catalog, starts a real Celery worker, verifies its Redis registration, and
  exercises the scheduler/dead-letter path. It intentionally performs no
  retailer HTTP requests because the seed has no real offers.
- Fly.io app `scenthunter` is production and must remain untouched.
- Fly.io app `sh-pilot-20261030` has one running `app` machine (shared CPU,
  2 GB RAM), no attached Managed Postgres cluster, and an empty Secrets list.
  The machine environment shown in the dashboard contains legacy Offer Engine
  settings; it does not prove that a Phase 5 worker is running.
- Do not deploy a worker image to `sh-pilot-20261030` until its current app
  command, image, release, volume/database dependencies, and cost impact have
  been checked. Do not use the production `fly.toml` for staging.

## Free-tier candidate services (verify limits in each provider console)

### PostgreSQL — Neon Free

Use a separate Neon project for staging only. The Free plan currently advertises
1 GB database storage per project and 100 CU-hours per project per month. It
scales to zero when idle. This is suitable for controlled tests, not a promise
of uninterrupted production availability.

Official plan details:
https://neon.com/pricing

### Redis — Upstash Free

Use a separate Upstash Redis database for staging only. The Free plan currently
advertises 256 MB data, 10 GB monthly bandwidth, and 500,000 commands per month.
Stay within the free quota; do not enable a paid plan or pay-as-you-go billing.

Official plan details:
https://upstash.com/pricing/redis

### Fly.io

Do not create another Fly Machine or resize the existing machine as part of this
zero-cost plan. Fly.io bills running Machines; the displayed 2 GB shared-cpu-1x
size is listed at approximately $11.11/month in the Amsterdam pricing table.
The existing machine may already incur charges. Check the Fly billing dashboard
before changing or reusing it.

Official pricing:
https://fly.io/docs/about/pricing/

## Required staging-only configuration

The Phase 5 worker expects:

- `SCENTHUNTER_CATALOG_DATABASE_URL`: Neon staging database URL (never the
  production database URL).
- `SCENTHUNTER_REDIS_URL`: Upstash staging Redis URL (TLS URL where supplied
  by Upstash).
- `SCENTHUNTER_DISCOVERY_TERMS_JSON`: leave empty for initial infrastructure
  verification; do not start retailer discovery.
- `SCENTHUNTER_MAIN_REFRESH_STORES`: leave unset/empty for initial
  infrastructure verification.
- `SCENTHUNTER_CONNECTOR_QUARANTINE_AFTER`: optional, defaults to 3.

Secrets must be entered directly in the hosting/provider secret manager. Never
commit credentials to Git, paste them into chat, or put them in screenshots.

## Safe execution order

1. Keep PR #343 open and draft. Do not merge it.
2. Create Neon and Upstash staging resources only on their Free plans; inspect
   billing/plan selection before confirming.
3. Apply Phase 2/Phase 5 Alembic migrations to the empty staging database only.
4. Run the worker integration check with an empty catalog of retailer offers.
   Confirm Celery worker registration and queue connectivity; no store discovery
   or price refresh is enabled.
5. Only after a successful isolated runtime check, decide whether a separate
   Fly worker deployment is worth its cost. A persistent Fly worker cannot be
   assumed free; do not start one without explicit cost approval.
6. Before any live retailer test, separately approve a specific store, test
   product, request rate, and data-retention policy.

## Important limitations

- GitHub Actions integration is disposable CI, not a persistent Celery service.
- Neon/Upstash free tiers have quotas and may suspend/limit usage.
- A worker running continuously on Fly.io is not covered by the free Neon or
  Upstash plans; Fly compute is a separate cost.
- No retailer ingestion, offer publication, production migration, production
  restart, or production secret change is authorized by this plan.
