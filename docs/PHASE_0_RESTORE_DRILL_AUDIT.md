# Phase 0 — operational database restore-drill audit

**Audit date:** 2026-11-24  
**Mode:** read-only inspection of Neon metadata, schemas and SQL data.  
**No restore, database write, branch deletion, queue retry, Fly machine, deploy or secret operation was performed.**

## 1. Correct recovery target

The operational application database is:

- Neon project: `Scenthunter` (`square-math-01119225`)
- Branch: `offer-first-postgres-cutover` (`br-red-night-ba3reqhp`)
- Database: `scenthunter_offerfirst`
- Current Alembic revision at audit time: `0006_postgres_ingestion_queue`

Do not substitute either `production/neondb` or the separate `offer-first-postgres-cutover/neondb` database. They are different datasets.

## 2. Existing recovery assets

Neon branch inventory showed these child branches of the operational branch:

| Branch | Parent timestamp (UTC) | Logical size | Audit interpretation |
|---|---|---:|---|
| `phase0-restore-drill-2026-11-24` | 06:54:53 | ~317 MB | Disposable clone created from operational branch data |
| `phase0-final-audit-backup-2026-11-24` | 06:33:44 | ~317 MB | Earlier clone |
| `phase0-verified-backup-2026-11-24-compute` | 06:14:48 | ~297 MB | Earlier clone |
| `phase0-final-snapshot-2026-11-24-1000` | 09:09:54 | ~319 MB | Later clone |
| `phase0-verified-backup-2026-11-24` | 06:14:36 | ~297 MB | Earlier clone |
| `phase0-backup-2026-11-24` | 05:32:25 | Not re-counted | Earlier clone |

These are Neon child branches with `init_source=parent-data`, not independent logical dumps. Their presence proves clone creation, not a completed application restore.

The project's manual snapshot inventory returned one snapshot, `scenthunter-phase0-before-cleanup-2026-11-24`, whose source is the default `production` branch, not the operational `offer-first-postgres-cutover` branch. The operational branch's automatic snapshot schedule returned an empty schedule.

## 3. Restore-drill branch integrity

Read-only inspection of `phase0-restore-drill-2026-11-24/scenthunter_offerfirst` confirmed the schema is at Alembic revision `0006_postgres_ingestion_queue` and the core catalog tables exist.

Counts on the drill clone at audit time:

| Entity | Drill clone |
|---|---:|
| Brands | 65 |
| Fragrances | 1,403 |
| Product variants | 556 |
| Stores | 10 |
| Offers | 163 |
| Price history | 8,882 |
| Raw ingestion observations | 48,400 |
| Ingestion runs | 50,443 |
| Match audit | 245 |
| Queue jobs | 173,365 |
| Queue schedule keys | 10 |
| Legacy product mappings | 1,417 |
| Legacy variant mappings | 547 |

At the same audit time, the live operational branch had 65 brands, 1,403 fragrances, 556 variants, 10 stores, 167 offers, 9,370 price-history rows, 50,283 raw observations, 52,409 ingestion runs, 262 match-audit rows and 176,137 queue jobs.

The difference is expected for a point-in-time clone created at 06:54:53 UTC; the live branch continued to change. Do not compare a historical clone to the current live row counts and call the difference data loss.

### Referential-integrity checks on the drill clone

The following read-only checks returned zero:

- Offers without a canonical variant.
- Offers without an external product ID.
- Offers without a valid store.
- Offers referencing a missing variant.
- Orphaned price-history rows.
- Raw ingestion rows without a valid store.

Queue state on the drill clone: 73,774 queued, 51,246 failed, 48,344 completed and 1 running. These are preserved historical/runtime states, not cleanup instructions. The presence of one running job in a clone must not trigger a retry or worker action.

## 4. What this proves — and what it does not

**Proven:**
- The operational Neon branch has several point-in-time child clones.
- The 06:54:53 UTC restore-drill clone can be opened and queried.
- Core catalog, offers, price history, raw observations, run history and queue tables are present.
- Key offer and price-history references are internally consistent in that clone.

**Not yet proven:**
- An independent logical backup/export can be restored into a clean database.
- The full application can connect to the restored database with the intended runtime configuration.
- API read paths and worker startup behave correctly against the restored database.
- Queue workers remain safely disabled during the drill and do not consume cloned pending jobs.
- A documented RPO/RTO and repeatable recovery procedure exists.
- Automated snapshots are configured for the operational branch.

A Neon child branch is a useful fast recovery point, but it is not by itself an application-level restore drill or an independent backup.

## 5. Required next recovery test

Use a newly approved, isolated recovery target, never the live operational branch:

1. Create a fresh disposable Neon branch from the operational branch at an explicitly recorded timestamp.
2. Keep all workers and schedulers disabled. Do not copy production secrets into the test environment.
3. Validate schema revision, table counts, foreign keys, offers and price-history references.
4. Configure a temporary application instance with read-only credentials against the disposable clone only.
5. Run API health and representative catalog/product/offer read smoke tests. Do not enqueue or execute jobs.
6. Confirm the app reads the expected catalog and offer data, then stop the temporary app.
7. Record the exact source timestamp, branch ID, database name, Alembic revision, counts, smoke-test output and elapsed time.
8. Separately test an independent logical export/restore if the recovery policy requires protection from project/branch-level failure.
9. Obtain approval before changing snapshot schedules, protecting branches, deleting old recovery branches, or touching Fly production.

## 6. Release gate for Phase 2

Do not apply Alembic revision `0007_catalog_identity` to the operational Neon database until:
- the isolated application restore test passes;
- the backup/export strategy and retention are documented;
- the operational branch has an agreed snapshot schedule or equivalent recovery policy;
- the migration and rollback plan is reviewed;
- the exact production branch/database and migration window are approved.

No production changes were made by this audit.


## 7. Read-only API smoke harness prepared

The Phase 2 branch now contains:

- `backend/scripts/restore_readonly_smoke.py`
- `.github/workflows/neon-restore-readonly-smoke.yml`

The harness imports only `app.api.catalog_search.router` into a minimal FastAPI app. It intentionally does not import `backend.main`, because the legacy main application's startup hooks can launch catalog bootstrap, discovery and hydration threads.

The manual workflow requires a repository Actions secret named `RESTORE_DRILL_DATABASE_URL` containing a dedicated SELECT-only connection URL for a disposable Neon clone. The workflow does not create a branch, role, credential or machine. Before the API calls, the script checks that the configured database name matches the requested expected name, PostgreSQL is in transaction read-only mode, the login role is not superuser/createdb/createrole/replication/bypassrls, and it has no database/schema CREATE or table write privileges. It then calls only `GET /api/catalog/status` and `GET /api/catalog/search`.

**Execution status (updated 2026-11-24):** the pull-request workflow run `45463636458` on commit `d08571d668038f453fdbf758b668e8ab84e3d107` completed successfully. Both jobs passed, including `Require a dedicated restore-clone credential` and `Run isolated API read-only smoke test`. The run therefore exercised the two catalog read endpoints against the configured disposable Neon clone using the dedicated credential and passed the harness's database-name, read-only transaction, role-privilege and read-path checks. The clone inspected by the harness was at schema revision `0006_postgres_ingestion_queue`; this does not test the new `0007_catalog_identity` API against that clone. This is application-level evidence for these two read paths only. It does **not** prove an independent logical export/restore, full production startup, worker recovery, or a complete disaster-recovery drill.


### 7.1 Exact minimum database grants for the smoke role

The two read endpoints currently query these seven canonical tables: `brands`,
`fragrances`, `product_variants`, `stores`, `offers`, `ingestion_raw`,
and `match_audit`. No sequence privileges are needed.

Run the following manually in the Neon SQL Editor **only on**
`phase0-restore-drill-2026-11-24` / database `scenthunter_offerfirst`.
Replace the password placeholder with a newly generated unique secret; do not
reuse the database owner password or paste the secret into GitHub issues/PRs:

```sql
CREATE ROLE scenthunter_restore_reader
  LOGIN PASSWORD '<GENERATE-A-UNIQUE-PASSWORD>'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

GRANT CONNECT ON DATABASE scenthunter_offerfirst
  TO scenthunter_restore_reader;
GRANT USAGE ON SCHEMA public TO scenthunter_restore_reader;
GRANT SELECT ON TABLE
  public.brands,
  public.fragrances,
  public.product_variants,
  public.stores,
  public.offers,
  public.ingestion_raw,
  public.match_audit
TO scenthunter_restore_reader;

ALTER ROLE scenthunter_restore_reader
  SET default_transaction_read_only = on;
```

After creating the role, obtain a connection URL for this role on the clone
from Neon Console and add it as the GitHub Actions repository secret
`RESTORE_DRILL_DATABASE_URL`. The expected database input remains
`scenthunter_offerfirst`. Do not use the owner URL. The role is disposable
and should be dropped/revoked after the drill once the workflow is complete.
