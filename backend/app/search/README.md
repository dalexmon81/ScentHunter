# Search layer

**Responsibility:** catalog-first user search and indexing adapters. User-facing search reads the canonical PostgreSQL catalog and already-published offers only; it never calls retailer websites, feed parsers or scraper modules.

Notino affiliate display URLs are validated through the pure `app.connectors.notino_links` utility. That helper has no network or scraper dependency. Search must not import the legacy affiliate feed parser directly.
