# SQLite canonical catalog — Phase 2

Phase 2 uses a dedicated SQLite database on the existing Fly volume:

- Canonical catalog: `/data/catalog/catalog.sqlite3`
- Existing storefront catalog: `/data/store_catalog.sqlite3` (untouched)
- Phase 0 queue: `/data/phase0/queue.sqlite3` (untouched)

The canonical database is isolated from both existing files. It uses WAL mode,
foreign-key enforcement, a 30-second busy timeout, and the same eight logical
tables intended for the future PostgreSQL schema:
`brands`, `fragrances`, `product_variants`, `stores`, `offers`,
`price_history`, `match_audit`, and `ingestion_runs`.

From the repository root:

```bash
cd backend
alembic upgrade head
python scripts/seed_catalog.py
# Review the dry-run report first. Import only with explicit approval:
python scripts/seed_catalog.py --apply
```

By default, `SCENTHUNTER_CATALOG_DATABASE_URL` or
`SCENTHUNTER_DATABASE_URL` may override the location, but the current Phase 2
engine rejects non-SQLite URLs. Without an override, it uses
`sqlite:////data/catalog/catalog.sqlite3`.

The seed imports brands, fragrances and explicitly declared variants only.
It does not import retailer offers, invent missing variants, or modify source
JSON, the storefront SQLite database, or the Phase 0 queue. It stops if any
product lacks explicit variant records. Missing tester/refill/gift-set flags
and GTINs are not inferred; unknown flags stay NULL. Dry-run is the default;
`--apply` is required to write canonical rows.

After an apply, the seed verifies all eight tables exist, reports row counts,
and checks that no active offer has a NULL price, empty/NULL URL, or NULL
availability. The initial seed intentionally imports no offers, so the
expected offer count is zero until a separately reviewed offer-import phase.

SQLite WAL is appropriate for the current single-writer/small-volume phase.
When multiple machines need concurrent shared writes, plan a separately
reviewed migration to Neon or Supabase PostgreSQL free tier. Do not enable a
paid Fly Managed PostgreSQL service.
