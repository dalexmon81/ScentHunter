# ScentHunter production release — 2026-11-24

Release authorized by the repository owner on 2026-11-24.

- Code baseline: `ea059d32e71ac1c09445e1743a9a080109235851` (PRs #918 and #919 merged).
- Release path: GitHub Actions `Fly Deploy` workflow.
- Expected operations: Fly deployment, Alembic migration to head, canonical catalog/store seed, health/search/worker queue verification.
- Pre-release database safety check: isolated Neon branch clone from the operational branch matched the source table counts at revision `0006_postgres_ingestion_queue`; this is a Neon branch clone, not an independent `pg_dump`/`pg_restore` drill.

This file records the release trigger and is not application configuration.


## 2026-11-24 — Notino bootstrap retry

The scheduled Notino PostgreSQL bootstrap failed before its script started: Fly Machine Exec exceeded its 30-second foreground deadline while launching the detached process. Increase only the launch-command timeout to 90 seconds in both the deploy-triggered bootstrap and the dedicated import workflow. Keep detached execution, durable exit-marker polling, and the script's transactional four-GTIN safety checks unchanged. The authorized release retry is triggered by a commit message containing `Notino PostgreSQL bootstrap`.
