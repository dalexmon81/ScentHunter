# Extraction

**Responsibility:** fetch a known retailer product reference or authorized feed item and preserve the source record needed for parsing and validation.

**Implementation ownership**
- `app.connectors` owns retailer-specific network transport, rate limits at the adapter boundary, raw response parsing and the normalized connector contract.
- `app.workers` invokes connector extraction only in background jobs and retains run/error accounting.
- `app.offers.ingestion` receives the extracted raw record, applies canonical matching and publication gates, and persists the evidence.

**Boundaries**
- Extraction operates on a known retailer identifier discovered earlier; it does not perform broad product discovery.
- It does not create canonical identities, choose variants, publish offers or update price history.
- It does not run in user-facing search requests.
- Do not copy scraper parsers into this package. Move source parsing only when the exact existing parser can be reused without behavioral change.

**Current adapters:** `app.connectors.notino_feed` and `app.connectors.legacy_scrapers`; existing scraper implementations remain in `backend/scrapers/`.
