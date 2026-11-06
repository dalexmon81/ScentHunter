# Phase 2 — PostgreSQL runtime policy

The isolated catalog database engine supports SQLite and PostgreSQL.

- SQLite remains the local/test default for backward compatibility.
- Staging and production-like catalog services should set
  `SCENTHUNTER_CATALOG_DATABASE_URL` to their PostgreSQL connection URL.
- Set `SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL=1` on those services to fail
  startup/configuration immediately if the resolved database URL is SQLite.
- The requirement flag accepts `1/0`, `true/false`, `yes/no`, and
  `on/off` (case-insensitive). Any other value fails closed.
- The database URL is never included in the error message.

Example environment (use the platform's secret manager for the URL):

```sh
SCENTHUNTER_CATALOG_DATABASE_URL=<PostgreSQL connection URL>
SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL=1
```

Do not set a real production URL in repository files. Do not migrate or alter
the legacy application's database as part of this policy change.

## Verification boundary

This policy prevents accidental SQLite fallback when enabled. It does not
prove that a particular deployment has the correct PostgreSQL secret, that
Alembic migrations have been applied, or that catalog data has been migrated.
Those require a separate staging runtime verification against the intended
database identity.
