# Phase 2 PostgreSQL Migration Plan

Status (2026-11-06): PostgreSQL support, staging fail-closed policy, and the dry-run-first importer are implemented and verified in disposable CI. No production database was contacted or modified; actual staging runtime identity and cutover remain unverified.

## 1. Current state and decision

The canonical Phase 2 catalog database factory in `backend/app/db.py` now accepts SQLite and PostgreSQL URLs. Its application default remains the isolated SQLite file `/data/catalog/catalog.sqlite3`; URL precedence is `SCENTHUNTER_CATALOG_DATABASE_URL`, then `SCENTHUNTER_DATABASE_URL`, then that default. The legacy retailer catalog remains a separate SQLite database (configured independently through `SCENTHUNTER_CATALOG_DB`). Never point canonical SQLAlchemy models at the legacy retailer database.

The Alembic chain now includes the initial catalog schema, raw ingestion and legacy ID maps, store-domain and variant metadata branches, their merge revision, identity/audit and ingestion-artifact/dead-letter additions, variant-size precision, ingestion uniqueness, offer TTL, and PostgreSQL catalog-search indexes. The repository's current migration graph has one head, resolved by the importer rather than hard-coded to an obsolete revision.

PostgreSQL support is implemented in the engine and exercised against disposable PostgreSQL 16 in CI. The isolated staging worker configuration sets `SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL=1`; it refuses to start without an explicit PostgreSQL URL. This is a fail-closed configuration guard, not proof that staging is deployed or running on that database.

**Decision:** PostgreSQL is the intended durable backend for the canonical catalog. SQLite remains the local/test default and compatibility fallback; the isolated staging worker requires PostgreSQL. Actual staging runtime identity, data import, and any production cutover remain separate acceptance gates. The legacy retailer catalog and its writer coordination remain separate and are not part of this migration.

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

- Implemented: `backend/app/db.py` accepts SQLite and PostgreSQL URLs.
- Implemented: preserve SQLite default and environment-variable precedence; staging workers require PostgreSQL through `SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL=1`.
- Normalize supported PostgreSQL URLs to the installed psycopg 3 driver without logging the URL.
- Apply SQLite PRAGMAs and SQLite-only connection arguments only to SQLite engines.
- Keep PostgreSQL pool health checks enabled and use bounded connection/pool settings appropriate to the Fly machine count.
- Reject unsupported dialects with a safe error that never echoes credentials.

### B. Runtime identity and observability

- Implemented: `backend/app/db_runtime_identity.py` reports masked identity for the caller's existing SQLite or PostgreSQL connection, including dialect, safe database identity, process/service, configuration source and timestamp.
- Never log hostname credentials, full DSNs, query parameters, or passwords.
- Runtime proof must be emitted from the exact SQLAlchemy connection used by the persistence operation, not a separately-created diagnostic connection.
- Ensure logging failures cannot silently redirect writes to another database.

### C. Alembic and schema parity

- Verified in disposable PostgreSQL CI: run all existing revisions from an empty database, check schema/model parity, constraints, indexes, UUID/JSON behavior, and verify a second `upgrade head` is a no-op. The integrated importer test also executes dry-run, apply, checksum and idempotent repeat.
- Do not use `Base.metadata.create_all()` as a substitute for versioned migrations.
- Add explicit tests for transaction rollback and foreign-key behavior.

### D. Data migration

- Implemented: `backend/scripts/migrate_canonical_sqlite_to_postgres.py` is a dry-run-first importer for the canonical SQLite database only. It resolves the current single Alembic head dynamically and fails closed if the migration graph has multiple heads.
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
