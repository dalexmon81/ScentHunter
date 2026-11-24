# Extraction

**Responsibility:** fetch a known retailer product reference and preserve the raw source record for downstream parsing and validation.

**Implementation ownership**
- `app.extraction.product.extract_product_record`: shared async boundary used by background workers; validates the stable external ID, preserves the source mapping and fills a missing external ID without rewriting source fields.
- `app.connectors`: retailer-specific transport and parsing (`parse_raw`) remain in the existing adapters.
- `app.workers`: invokes extraction only in background jobs and retains run/error accounting.
- `app.offers.ingestion`: parses/normalizes the extracted raw record, resolves canonical identity and applies publication gates.

**Boundaries**
- Extraction operates on a known retailer identifier; broad discovery and pagination belong to `app.discovery`.
- It does not create canonical identities, choose variants, publish offers or update price history.
- It does not run in user-facing search requests.
- Do not copy scraper parsers into this package; source parsing stays in the exact existing connector implementation.

**Tests:** `backend/tests/test_extraction_product.py`, plus the Notino and legacy worker runtime regression suites.
