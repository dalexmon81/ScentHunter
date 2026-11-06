# Canonical catalog database runtime policy

## Runtime selection

The Phase 2 canonical catalog database supports SQLite and PostgreSQL through
`backend/app/db.py`.

Database URL precedence is:

1. `SCENTHUNTER_CATALOG_DATABASE_URL`
2. `SCENTHUNTER_DATABASE_URL`
3. Application default: `sqlite:////data/catalog/catalog.sqlite3`

The SQLite default remains useful for local development and isolated tests. It
must not be mistaken for proof that a deployed staging worker is using
PostgreSQL.

The isolated staging worker configuration (`fly.staging-workers.toml`) sets
`SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL=1`. Before those workers can start,
`SCENTHUNTER_CATALOG_DATABASE_URL` must be supplied through the staging
environment and must resolve to PostgreSQL. A missing URL or SQLite URL fails
closed. This guard does not deploy the workers or change production settings.

## Database separation

Keep the canonical catalog separate from the existing storefront database and
the Phase 0 queue:

- Canonical catalog local default: `/data/catalog/catalog.sqlite3`
- Existing storefront catalog: `/data/store_catalog.sqlite3` (untouched)
- Phase 0 queue: `/data/phase0/queue.sqlite3` (untouched)

Never point the canonical SQLAlchemy models at the legacy retailer catalog.

## Migrations and seed

From the repository root:

```bash
cd backend
alembic upgrade head
python scripts/seed_catalog.py
# Review the dry-run report first. Import only with explicit approval:
python scripts/seed_catalog.py --apply
```

The seed imports brands, fragrances and explicitly declared variants only. It
does not import retailer offers, invent missing variants, or modify source JSON,
the storefront SQLite database, or the Phase 0 queue. Missing tester/refill/
gift-set flags and GTINs are not inferred; unknown flags stay NULL. Dry-run is
the default; `--apply` is required to write canonical rows.

The initial seed intentionally imports no offers. Offers enter the canonical
catalog only through the separately validated ingestion and promotion pipeline.

## SQLite-to-PostgreSQL importer

`backend/scripts/migrate_canonical_sqlite_to_postgres.py` is dry-run-first:

- Opens the SQLite source read-only.
- Requires a dedicated PostgreSQL target in
  `SCENTHUNTER_MIGRATION_TARGET_DATABASE_URL`.
- Requires source and target to match the repository's current single Alembic
  head and canonical schema.
- Checks foreign keys, row identities and checksums.
- Writes only with `--apply` and an exact `--confirm-target` database name.
- Applies inside a destination transaction and supports an idempotent repeat.

The importer does not migrate the legacy storefront database or its
retailer-discovery/hydration tables.

## Verification boundary

The integrated disposable PostgreSQL workflow, including the SQLite importer
dry-run/apply/repeat test, passed in
[run #42281155461](https://github.com/dalexmon81/ScentHunter/actions/runs/42281155461).

That is CI evidence only. It does not prove the identity of a running staging
database, a real staging data import, or a production cutover. Those require
separate operational evidence and approval.
