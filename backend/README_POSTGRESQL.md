# Canonical catalog database runtime

The SQLAlchemy application database is configured explicitly through
`SCENTHUNTER_CATALOG_DATABASE_URL` (preferred) or
`SCENTHUNTER_DATABASE_URL`.

## Runtime rules

- PostgreSQL with the `psycopg 3` driver is the required application runtime.
- Set `SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL=1` in production and recovery
  smoke-test environments. This rejects SQLite URLs.
- SQLite is supported only when a caller explicitly supplies a SQLite URL for
  isolated tests or local tools; there is no implicit local-database fallback.
- The canonical SQLAlchemy runtime is separate from legacy storefront and
  Phase 0 SQLite files. Do not infer that those SQLite files are the canonical
  production database.
- Do not run Alembic upgrades, seed commands, ingestion, discovery, hydration,
  queue workers or schedulers during a restore read-only smoke test.

## Isolated restore API smoke test

The workflow
`.github/workflows/neon-restore-readonly-smoke.yml` builds a minimal FastAPI
application from `app.api.catalog_search.router` only. It deliberately does
not import `backend.main`, whose startup hooks can launch bootstrap,
discovery and hydration workers.

Before dispatching the workflow:

1. Create or identify a disposable Neon child branch cloned from the intended
   operational branch, and record its exact branch ID and parent timestamp.
2. Create a dedicated PostgreSQL role on that clone with SELECT-only access to
   the catalog tables required by the two read endpoints. Do not use the
   database owner, a superuser, the production URL or a production secret.
3. Store the clone-only connection URL as the GitHub Actions secret
   `RESTORE_DRILL_DATABASE_URL`. Restrict the secret to the repository and
   remove it after the drill.
4. Dispatch the workflow only after confirming that the secret targets the
   disposable clone and that its database name matches the input.

The script additionally enforces PostgreSQL, transaction read-only mode,
non-superuser/non-admin role attributes, no database/schema CREATE privilege,
and no table write grants. It then calls only:
- `GET /api/catalog/status`
- `GET /api/catalog/search?q=<search_query>`

It does not import the legacy main application, invoke retailer connectors,
enqueue jobs, or run workers. The workflow does not create Neon branches,
roles, credentials or infrastructure. A passing run proves these two API
read paths work against the configured clone; it does not prove independent
logical backup/export recovery or a full production application restore.

## Production release gate

Do not apply revision `0007_catalog_identity` to the operational Neon branch
until the isolated API smoke test, independent backup/export recovery strategy,
retention policy, rollback review and explicit production approval are complete.
