# Extraction

**Responsibility:** fetch a known retailer product reference or existing offer observation and preserve the returned source evidence.

**Implementation ownership**
- `app.extraction.product`: shared async boundary for fetching one known product or price/stock observation; validates identifiers and result shape without changing retailer fields.
- `app.connectors`: retailer-specific network transport, authorized feed access, parsing and normalized connector contract.
- `app.workers`: invokes extraction only in background jobs and retains run/error accounting.
- `app.offers.ingestion`: receives extracted raw product records, applies canonical matching and publication gates, and persists evidence.
- `app.pricing`: validates and persists refresh observations for existing offers.

**Boundaries**
- Extraction operates on a known retailer identifier discovered earlier; it does not perform broad product discovery.
- It does not create canonical identities, choose variants, publish offers or update price history.
- It does not run in user-facing search requests.
- Do not copy scraper parsers into this package. Existing source parsers remain in `app.connectors` and `backend/scrapers/`.

**Tests:** `backend/tests/test_extraction_product.py`, `backend/tests/test_notino_worker_runtime.py`, and `backend/tests/test_legacy_worker_runtime.py`.
