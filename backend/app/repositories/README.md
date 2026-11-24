# Repositories layer

**Responsibility:** database queries and transaction-scoped persistence operations. Repositories own SQLAlchemy access and expose stable methods to domain services and workers; callers own transaction boundaries unless a method explicitly documents otherwise.

**Current extracted repository operation**
- `app.repositories.ingestion_runs`: create, update and close `IngestionRun` records with validated counters and bounded errors. It never commits, queues work or performs network I/O.

**Other persistence boundaries**
- `app.offers.persistence` owns the atomic raw-ingestion/match/offer publication gate because it enforces domain invariants across multiple records.
- `app.pricing.offer_refresh` owns verified existing-offer refresh and price-history invariants.
- `app.models` remains the SQLAlchemy entity layer.

**Migration rule:** extract database access incrementally where it reduces direct ORM coupling without splitting atomic transactions or creating duplicate query paths. `app.workers.ingestion_run` is a temporary compatibility re-export only.

**Tests:** `backend/tests/test_catalog_ingestion_run.py`.
