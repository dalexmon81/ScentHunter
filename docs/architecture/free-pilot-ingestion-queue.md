# Free single-machine ingestion queue (isolated pilot)

The pilot uses a durable SQLite queue on its existing Fly volume. It does not
require Redis, Managed Postgres, a second Fly machine, or a paid add-on.

- Queue DB: `/data/catalog/ingestion_queue.sqlite3`
- Canonical catalog DB: `/data/catalog/catalog.sqlite3` (separate file)
- Backend: `SCENTHUNTER_QUEUE_BACKEND=sqlite`
- Worker: one process in the existing pilot machine, started by `Dockerfile.pilot`
- Initial scheduled connector: active canonical store with slug `notino-fr`
- Discovery cadence: once per UTC day; each discovery page queues its product
  fetches through the same durable SQLite queue.
- Retry policy: five attempts with bounded exponential delay; stale running jobs
  are returned to the queue or marked failed after the attempt limit.

The queue is deliberately single-machine/single-worker. Do not scale the pilot
to multiple machines while using this local SQLite queue and volume. The
catalog's existing canonical matching and publication validation remain the
only path to a published offer. Unmatched and invalid source rows are not
published.

For local tests:

```bash
cd backend
PYTHONPATH=. python -m unittest discover -s tests -p 'test_sqlite_ingestion_queue.py' -v\nPYTHONPATH=. python -m unittest discover -s tests -p 'test_catalog_worker_queue.py' -v\nPYTHONPATH=. python -m unittest discover -s tests -p 'test_notino_worker_runtime.py' -v
```

Redis/Celery remains available as an optional future backend by setting
`SCENTHUNTER_QUEUE_BACKEND=redis` and a verified `SCENTHUNTER_REDIS_URL`.
