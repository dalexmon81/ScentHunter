# Extraction

**Responsibility:** fetch a known retailer product reference or a known offer's price/stock observation and preserve the raw source evidence.

**Implementation ownership**
- `app.extraction.product.extract_product_record`: shared async boundary for product-page/feed-record fetches; validates the stable external ID, preserves the source mapping and fills a missing external ID without rewriting source fields.
- `app.extraction.product.extract_price_stock_observation`: shared async boundary for price/stock refresh fetches; returns the source observation unchanged as a mapping.
- `app.connectors`: retailer-specific transport and parsing (`parse_raw`) remain in the existing adapters.
- `app.workers`: invokes extraction only in background jobs and retains run/error accounting.
- `app.offers.ingestion`: parses/normalizes product records, resolves canonical identity and applies publication gates.
- `app.pricing`: validates and persists observations for already-published offers without rematching canonical identity.

**Boundaries**
- Extraction operates on a known retailer identifier; broad discovery and pagination belong to `app.discovery`.
- It does not create canonical identities, choose variants, publish offers or update price history.
- It does not run in user-facing search requests.
- Do not copy scraper parsers into this package; source parsing stays in the exact existing connector implementation.

**Tests:** `backend/tests/test_extraction_product.py`, plus the Notino and legacy worker runtime regression suites.
