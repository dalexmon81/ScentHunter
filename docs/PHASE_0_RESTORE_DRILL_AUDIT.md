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
