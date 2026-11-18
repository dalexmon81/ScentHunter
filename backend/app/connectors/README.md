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
