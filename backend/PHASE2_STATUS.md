# Phase 2 — Database and data model status

Branch: `refactor/catalog-first-architecture`

## Repository inspection (2026-11-04)

The current branch contains the Phase 1 directory scaffolding under `backend/app/` and a placeholder `backend/alembic/README.md`.

The following files are **not yet present on this branch**:
- SQLAlchemy database engine/session configuration
- SQLAlchemy catalog models
- `alembic.ini`, Alembic `env.py`, and versioned migrations
- PostgreSQL/Alembic/psycopg dependencies in `backend/requirements.txt`
- Catalog seed/import and schema verification scripts

The Alembic README explicitly says that no database schema is introduced in this scaffolding step. The backend requirements inspected on this branch do not include SQLAlchemy, Alembic, or a PostgreSQL driver.

## Exit gate

Do not mark Phase 2 complete until all of the following are demonstrated against the actual PostgreSQL database:
1. PostgreSQL engine/session configuration is implemented and secrets are environment-based.
2. SQLAlchemy models cover brands, fragrances, product variants, stores, offers, price history, match audit, and ingestion runs.
3. Alembic has a complete initial migration and can upgrade a clean PostgreSQL database to head.
4. Required foreign keys, uniqueness constraints, checks, and indexes are verified in PostgreSQL.
5. The legacy catalog importer supports a non-destructive dry run and an explicit apply mode; a backup is retained.
6. Verification reports the actual database schema and seed counts.
7. Phase 2 schema and importer tests pass in CI, ideally against PostgreSQL rather than SQLite alone.
8. Runtime/deployment configuration provides PostgreSQL and the migration command is documented.

## Safety note

Do not run destructive migrations, point a seed importer at production by default, or commit credentials. A repository scaffold or SQLite analogue is not evidence that PostgreSQL migrations have been applied.

## Current conclusion

**Phase 2 is not complete on this branch based on the files currently committed.** The work should continue from this branch and be verified against a real PostgreSQL instance before Phase 3 begins.
