# Phase 5 — Redis/Celery ingestion pipeline

## Architecture

The ingestion runtime is opt-in and separate from the API process. Redis is the
Celery broker; Celery Beat schedules background work. Six queues are declared:
`discovery`, `offers`, `validation`, `matching`, `refresh`, and
`dead_letter`.

Task flow:

1. `discover_store_products` runs a store connector and queues each discovered
   retailer product.
2. `fetch_store_offers` fetches offer records and stages them idempotently in
   `ingestion_raw`.
3. `normalize_offer` applies the canonical product normalizer.
4. `validate_offer` checks required evidence, URL, price, currency, timestamp
   and availability without inventing missing values.
5. `match_offer_to_variant` delegates to the existing conservative UUID matcher.
6. Publication remains a separate explicit worker; ingestion never publishes
   an unmatched or unvalidated offer.
7. `refresh_price_and_stock` stages a new observation for a known retailer ID.
8. Failed tasks are retried with exponential backoff and jitter. Exhausted tasks
   are sent to the `dead_letter` queue and repeated store failures trigger the
   store-scoped quarantine check.

The `_raw_evidence` envelope stores connector discovery evidence and the parsed
record alongside normalized fields so the matching/promotion contracts remain
backwards-compatible. Exact HTTP response bodies (especially HTML downloaded
inside legacy scraper functions) are not yet guaranteed to be captured by every
connector. A follow-on raw artifact capture adapter is required before claiming
full byte-for-byte XML/CSV/HTML replay coverage.

## Cadence

Celery Beat defaults:
- Product discovery: every 24 hours.
- New offer collection: every 8 hours.
- Main-store price/stock refresh: every 30 minutes, only for stores explicitly
  listed in `SCENTHUNTER_MAIN_REFRESH_STORES`.

An on-demand product-page check can call
`refresh_price_and_stock(store_key, offer_id)` directly. The HTTP product
detail endpoint is not wired to dispatch that task yet.

## Configuration

Required:
- `SCENTHUNTER_CATALOG_DATABASE_URL`: existing Phase 2 catalog database URL.
- `SCENTHUNTER_REDIS_URL`: Redis broker URL (default local Redis).
- `SCENTHUNTER_DISCOVERY_TERMS_JSON`: optional JSON object mapping store slugs
  to discovery search terms. Example:
  `{"deloox":["Dior Sauvage 100 ml"],"sabina":["Chanel No 5"]}`.
- `SCENTHUNTER_MAIN_REFRESH_STORES`: comma-separated store slugs opted into
  the 30-minute refresh schedule.
- `SCENTHUNTER_CONNECTOR_QUARANTINE_AFTER`: consecutive failures before
  quarantine (default 3).

No schema migration or production service is run automatically. The deployment
must supply the existing catalog DB URL and explicit store configuration.

## Local opt-in

```bash
docker compose -f docker-compose.ingestion.yml up -d redis celery-worker celery-beat
```

This starts only the optional ingestion services. It does not deploy the API or
enable user-search-time scraping.

## Verification

The Phase 5 GitHub Actions workflow compiles the worker/connector modules and
runs the ingestion, matching, promotion and queue configuration tests. Passing
fixture tests do not prove live retailer credentials, live store reachability,
or production worker activation.
