# Phase 2 PostgreSQL Migration Plan

Status: preparation only — no production database was contacted or modified.

## 1. Current state and decision

The canonical Phase 2 catalog is currently configured by `backend/app/db.py` to use the isolated SQLite file `/data/catalog/catalog.sqlite3` by default. The legacy retailer catalog is a separate SQLite database (currently configured by `SCENTHUNTER_CATALOG_DB` in the Fly app configuration). Do not point the canonical SQLAlchemy models at the legacy retailer database.

The repository already contains three Alembic revisions:

- `0001_initial_catalog`: brands, fragrances, product variants, stores, offers, price history, match audit and ingestion runs.
- `0002_ingestion_raw`: raw ingestion staging, legacy ID maps and the offer-to-raw relationship.
- `0003_store_domain`: retailer domain on stores.

The current application database factory explicitly rejects non-SQLite URLs. PostgreSQL support in model/migration definitions and the installed `psycopg[binary]` dependency are not, by themselves, proof that the application can safely run on PostgreSQL.

**Decision:** PostgreSQL is the intended durable backend for the canonical catalog. SQLite remains the current production backend until the readiness gates below pass. The legacy retailer catalog and its writer coordination remain separate and are not part of this migration.

## 2. Non-negotiable safety boundaries

1. No production database connection, SQL query, schema migration, seed, import, or write is part of this preparation branch.
2. Do not add a production PostgreSQL URL, password, token, or other credential to source control, workflow logs, PR text, or test fixtures.
3. Do not change Fly secrets, volumes, machines, deployment configuration, or production environment variables in this phase.
4. Do not merge this branch or deploy it until the migration implementation and its test evidence have been reviewed.
5. Keep the existing SQLite canonical database intact and take a verified, restorable backup before any future cutover.
6. Keep the legacy SQLite retailer catalog at its existing path and preserve its writer lock behavior. Never migrate or repoint it as part of the canonical catalog cutover.
7. PR #324 remains open and untouched.

## 3. Required implementation work before cutover

### A. Database URL and engine support

- Extend `backend/app/db.py` to accept SQLite and PostgreSQL URLs.
- Preserve the existing SQLite default and current environment-variable precedence until an explicit cutover is approved.
- Normalize supported PostgreSQL URLs to the installed psycopg 3 driver without logging the URL.
- Apply SQLite PRAGMAs and SQLite-only connection arguments only to SQLite engines.
- Keep PostgreSQL pool health checks enabled and use bounded connection/pool settings appropriate to the Fly machine count.
- Reject unsupported dialects with a safe error that never echoes credentials.

### B. Runtime identity and observability

- Generalize `backend/app/db_runtime_identity.py`: retain the current same-connection SQLite identity check; for PostgreSQL report only dialect, server/database identity fields that are safe, process, service, configuration source and timestamp.
- Never log hostname credentials, full DSNs, query parameters, or passwords.
- Runtime proof must be emitted from the exact SQLAlchemy connection used by the persistence operation, not a separately-created diagnostic connection.
- Ensure logging failures cannot silently redirect writes to another database.

### C. Alembic and schema parity

- Run all existing revisions against disposable PostgreSQL in CI, from an empty database.
- Verify `alembic upgrade head`, Alembic head, model metadata parity, constraints, indexes, UUID and JSON behavior.
- Verify a second `upgrade head` is a no-op.
- Do not use `Base.metadata.create_all()` as a substitute for versioned migrations.
- Add explicit tests for transaction rollback and foreign-key behavior.

### D. Data migration

- Build a repeatable, resumable, dry-run-first importer for the canonical SQLite database only.
- Preserve UUID primary keys and foreign keys; import in dependency order: brands, fragrances, variants, stores, legacy ID maps, ingestion raw, offers, price history, match audit, ingestion runs.
- Preserve nullable values, timestamps, status values, JSON payloads, and exact currency/price precision.
- Use deterministic ordering and idempotent upserts; never invent missing variants or match relationships.
- Record source counts, destination counts, rejected rows, duplicate keys and checksums in a migration report.
- Do not import retailer discovery/hydration tables from the legacy SQLite database.
- Require zero unexplained row-count differences and zero foreign-key violations before cutover.

### E. Application compatibility

- Exercise Bplatz staging, matching, promotion, offer upsert, price-history append and audit creation on PostgreSQL using disposable test data.
- Check SQLAlchemy queries for SQLite-only SQL, implicit row behavior, JSON differences and concurrency assumptions.
- Confirm the API/search path still reads the intended catalog and never falls back to live retailer searches.
- Confirm the Phase 2 worker's runtime database identity matches the configured canonical database.

## 4. Test matrix (CI only)

| Area | Required evidence |
| --- | --- |
| URL parsing | SQLite file, SQLite memory, PostgreSQL URL, missing URL, unsupported dialect; no credential leakage |
| Engine setup | SQLite PRAGMAs only on SQLite; PostgreSQL engine creation does not execute PRAGMAs |
| Alembic | Empty PostgreSQL database upgrades to head; repeat upgrade is a no-op |
| Schema | Tables, columns, constraints, indexes and foreign keys match the ORM contract |
| Persistence | Stage, match, promote, upsert, history and audit pass on PostgreSQL |
| Transactions | Rollback leaves no partial raw/offer/history/audit records |
| Importer | Dry run is read-only; repeat import is idempotent; counts and checksums reconcile |
| Isolation | Legacy retailer SQLite path and writer-lock tests remain unchanged |
| Security | Logs and test failures never expose DSNs or credentials |

## 5. Cutover runbook (future, separately authorized)

1. Provision a dedicated PostgreSQL database and private connection secret. Do not reuse the legacy SQLite volume or database.
2. Capture and verify a consistent backup of the canonical SQLite file; retain an untouched rollback copy.
3. Pause only the Phase 2 canonical writer, not unrelated retailer discovery or legacy catalog services.
4. Run Alembic migrations against PostgreSQL and verify the expected head.
5. Run the importer in dry-run mode; review counts, rejects, checksums and FK plan.
6. Apply the import once, then verify source/destination counts, checksums, foreign keys, integrity, offer validity and representative record links.
7. Switch only the Phase 2 canonical database configuration to PostgreSQL.
8. Restart the relevant app/worker and verify runtime identity from the actual persistence connection.
9. Run a bounded normal-worker observation; verify raw ingestion, offer upsert, price history and audit deltas, plus health/search behavior.
10. Keep SQLite read-only and available for rollback during the agreed observation window. Do not dual-write.
11. If any gate fails, stop Phase 2 writers, restore the SQLite configuration and restart on the untouched SQLite database. Reconcile any post-cutover observations before retrying; do not blindly replay writes.
12. Remove the SQLite rollback copy only after explicit acceptance and a separately approved retention decision.

## 6. Exit criteria

The PostgreSQL migration is complete only when all of the following are evidenced:

- CI test matrix is green against a real disposable PostgreSQL service.
- Alembic is at the expected head and schema parity is verified.
- Canonical data import reconciles exactly, with no unexplained rejects or foreign-key violations.
- Runtime logs prove the actual Phase 2 worker uses the intended PostgreSQL database without leaking connection details.
- A normal Bplatz worker cycle creates/updates the expected raw, offer, price-history and audit records.
- Health and catalog search checks pass after cutover.
- Rollback remains possible and documented.

Until then, Phase 2 remains open. No Phase 3 work should depend on PostgreSQL being available.
