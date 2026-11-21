# Offer-First PostgreSQL queue deployment

The PostgreSQL ingestion queue is deployed through the standard Fly Deploy workflow on pushes to `main` that change deployable paths.

The Fly release command applies Alembic migrations before application rollout. The queue worker is a separate Fly process and must be verified independently after deployment.

Production acceptance checks:

1. Confirm Alembic revision `0006_postgres_ingestion_queue`.
2. Confirm `ingestion_queue_jobs` and `ingestion_queue_schedule` exist in `scenthunter_offerfirst`.
3. Confirm the dedicated `worker` process is started and its logs show successful PostgreSQL queue polling.
4. Confirm a supported connector has a configured discovery seed before expecting discovery jobs.
5. Verify a newly ingested or refreshed offer in PostgreSQL before considering ingestion operational.

Do not run the manual-only catalog import or runtime cutover workflows as part of an ordinary queue deployment.
