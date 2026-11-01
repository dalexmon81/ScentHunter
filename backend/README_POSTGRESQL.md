# PostgreSQL catalog database — Phase 2

This is a separate canonical catalog/offer database. The current production
SQLite catalog at `/data/store_catalog.sqlite3` remains untouched and remains
the active source for existing search and ingestion during this phase.

Set `SCENTHUNTER_DATABASE_URL` to a PostgreSQL connection URL; never commit
credentials. From the repository root:

```bash
cd backend
alembic upgrade head
python scripts/seed_catalog.py
# Inspect the dry-run report; only after review:
python scripts/seed_catalog.py --apply
```

The seed imports brands, fragrances and explicitly declared variants only.
It does not import retailer offers, invent missing variants, or modify either
the source JSON or legacy SQLite database. It stops if any product lacks
explicit variant records. Missing tester/refill/gift-set flags and GTINs are
not inferred; unknown flags stay NULL. The default command is dry-run only.
Use `--apply` only after reviewing the catalog migration report and approving
the source identities.

Do not repoint `SCENTHUNTER_CATALOG_DB`, remove the Fly volume, enable the
new database in normal search, or cut over production as part of Phase 2.
Unmatched offers may have a NULL variant reference until reviewed. Prices use
fixed-precision NUMERIC and timestamps are timezone-aware.
