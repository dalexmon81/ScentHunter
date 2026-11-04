# Catalog-first search

The catalog search API is mounted at `GET /api/search`. It reads canonical
PostgreSQL catalog records and never calls retailer connectors or scrapers.

## Search behavior

- PostgreSQL native full-text search is the default source of truth. GIN indexes
  cover brand, fragrance and structured olfactory notes.
- Multi-token queries can match across fields, so `Dior Sauvage` matches the
  Dior brand and Sauvage fragrance together.
- SQLite LIKE is retained only for local development and unit tests.
- Optional Meilisearch adds typo tolerance and fast faceted lookup. Configure
  `MEILISEARCH_URL` and optional `MEILISEARCH_API_KEY`, then run
  `python scripts/reindex_meilisearch.py` from `backend/`.
- If Meilisearch is not configured, empty, or unavailable, PostgreSQL FTS is
  used. Meilisearch is an accelerator, never the canonical data store.
- Results group all canonical variants under one fragrance. If there is more
  than one variant, `variant_selection_required` is true.
- A matching fragrance with no fresh published offers is still returned with
  an explicit no-offer message.
- Only active offers from active stores, explicitly published, in stock and
  captured within the freshness window are returned by search.

## Indexed attributes

Brand, fragrance, concentration, format, olfactory family, olfactory notes,
gender, availability, minimum EUR price, minimum price by currency, store count,
store slugs, country and currency.

## Endpoints

- `GET /api/search?q=Dior%20Sauvage`
- `GET /products/{slug}`
- `GET /products/{slug}/offers?variant_id=...`
- `GET /brands`
- `GET /stores`
- `GET /offers?storeId=...&availability=in_stock`

The product detail endpoint returns all variants. The offers endpoint returns
HTTP 409 with the available variant choices when a product has multiple
variants and no variant ID was selected. Expired offers are labeled
`dato_da_verificare`; stores that are not active are excluded.

## Filters

Supported search filters: `brand`, `family`, `gender`,
`concentration`, `format` (`tester`, `refill`, `gift_set`, `mini`),
`store`, `availability`, `country`, `currency`, `min_price`,
`max_price`, `limit` and `offset`.

## Migration safety

The existing legacy `/search` endpoint remains unchanged during migration.
Cutover requires comparison of catalog coverage, match quality, offer freshness
and latency before traffic is redirected.
