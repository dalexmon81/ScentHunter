# Connectors layer

One adapter per retailer. A connector is called by background ingestion workers,
never by a user-facing search endpoint, and never writes directly to the canonical
database.

## Shared contract

Implement `app.connectors.StoreConnector` and define a stable, lowercase
`store_key`. Each implementation must provide:

- `discover_products(cursor, limit)`: return stable retailer IDs and absolute product URLs.
- `fetch_product(external_product_id)`: fetch one retailer product record.
- `fetch_offers(product_key)`: return raw offer records for that product.
- `fetch_price_and_stock(offer_id)`: refresh a known offer.
- `parse_raw(raw)`: map retailer-specific fields to the shared offer field names.
- `validate_offer(offer)`: common publication checks; override only to add stricter store-specific checks.

The common validation gate requires an absolute HTTP(S) product URL, a positive
finite price, a three-letter uppercase currency code, and explicit availability
(`in_stock` or `out_of_stock`). It intentionally rejects unknown stock states.

## Pure connector utilities and import boundary

`app.connectors.notino_links` contains the pure Notino/CJ URL validation contract used by read-only search and the authorized feed parser. It has no network or scraper dependency. Package exports are lazy: importing this utility does not eagerly import the retailer adapters or legacy scraper modules.

## Responsibilities outside the connector

The ingestion worker/orchestrator owns rate limiting, bounded retries with
exponential backoff, circuit breaking/quarantine, raw response retention,
normalization/matching, database transactions, and dead-letter handling. Keep
network I/O out of API request handlers. Never treat a successful parse as proof
that an offer is safe to publish.

## Tests

Run from `backend/`:

```bash
python -m unittest discover -s tests -p 'test_store_connector_contract.py' -v
```

Every retailer adapter must add fixture tests for product parsing, variants,
out-of-stock, missing price/URL/stock, and a changed retailer response.


## Existing scraper adapters

`legacy_scrapers.py` wraps the existing Deloox, Sabina, Easycosmetic and
Parfum-Zentrum parsers. It uses operator-provided discovery queries from
`SCENTHUNTER_DISCOVERY_QUERIES_DELOOX`,
`SCENTHUNTER_DISCOVERY_QUERIES_SABINA`,
`SCENTHUNTER_DISCOVERY_QUERIES_EASYCOSMETIC`, and
`SCENTHUNTER_DISCOVERY_QUERIES_PARFUMZENTRUM` respectively. Values are
semicolon-separated query seeds. A missing seed list fails closed and the
scheduler will not enqueue discovery for that store.

The adapters use each product URL as the stable external product identifier,
re-fetch known product URLs in background fetch/refresh jobs, and retain the
legacy parser output as raw evidence. A parser's default EUR fallback is not
treated as source evidence: publication requires an explicit `priceCurrency`
field in the retained JSON-LD (or an explicit provenance field from a source).
Unknown availability remains unknown and is rejected by the shared validation
gate. Canonical matching and persistence stay in
`app.offers.ingestion`.
