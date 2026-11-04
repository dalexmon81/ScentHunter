# Catalog-first search

The catalog search API is mounted at `GET /api/search`. It reads the Phase 2
canonical PostgreSQL catalog and never calls a retailer connector or scraper.

## Search behavior

- PostgreSQL uses `plainto_tsquery('simple', ...)` over brand and fragrance
  names. GIN indexes are added by Alembic revision
  `0009_catalog_search_fts`.
- SQLite uses a LIKE-based fallback for local development and unit tests.
- Only offers with `status=active`, `publication_status=published`, an active
  store, explicit `in_stock` availability, and evidence captured within the
  freshness window are returned.
- Products are grouped by canonical variant. Each result includes its current
  offers, store, price, currency, availability, URL and capture timestamp.
- No match is guessed from retailer websites at request time.

## Filters

Supported query parameters: `brand`, `family`, `gender`,
`concentration`, `format` (`tester`, `refill`, `gift_set`, `mini`),
`store`, `availability`, `country`, `currency`, `min_price`,
`max_price`, `limit` and `offset`.

## Example

```http
GET /api/search?q=Sauvage&country=FR&currency=EUR&min_price=50&max_price=120
```

The existing legacy `/search` endpoint is intentionally unchanged during
migration. Cutover requires comparison of catalog coverage, match quality,
offer freshness and latency before traffic is redirected.
