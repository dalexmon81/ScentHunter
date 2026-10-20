# ScentHunter Next Engine (isolated prototype)

A separate Python package for a staged replacement of catalog ingestion. It models retailer offers, normalizes product identity and currency, stores observations in a separate SQLite repository, and supports a shadow-comparison stage before migration.

## Current status

- Offline fixture tests: **31 passed**.
- Python compilation: passed.
- Deloox adapter: now handles Product JSON-LD in nested graphs, `AggregateOffer.lowPrice`, and explicitly marked product-price metadata as a fallback.
- The adapter validates Deloox host and product path before parsing.
- Fetch contract tests cover timeout classification, HTTP 403/404/410/429/5xx handling, empty bodies and untrusted redirects.
- Parser request-state handling was hardened so a failed parse cannot reuse a previous redirect target.

## Not yet production-ready

The package is not mounted into the live FastAPI app, has not been tested against live Deloox HTML in this run, and has not been deployed. The legacy catalog, scrapers, database and queues remain untouched. Do not enable the new API in production yet.

See `INSTALLAZIONE.md` for safe next steps, `SQLITE_EXPORT.md` for the read-only legacy database exporter, and `TEST_RESULTS.txt` for exact verification scope.


## Offline shadow comparison

Schema-aware, read-only SQLite snapshot exporters are available in `scenthunter_next_engine.sqlite_export` (legacy catalog) and `scenthunter_next_engine.next_sqlite_export` (new engine). It opens only the explicit database path with SQLite `mode=ro`, and it never imports the legacy engine or runs migrations. Its output can be passed to `scenthunter_next_engine.shadow_runner` for offline comparison. See `SQLITE_EXPORT.md` and `SHADOW_RUNNER.md`. Current offline suite: 31 tests passing.
