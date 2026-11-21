# ScentHunter 2.0 — Retailer connector inventory (source audit)

Audit basis: repository `main`, inspected 2026-11-21. This document distinguishes code presence from proven operational health. No production services or databases were changed.

## Confirmed retailer set

The project scope is nine retailers:
1. Bplatz
2. Deloox
3. Easycosmetic
4. Notino
5. Orioudh
6. Parfumcity
7. Parfumzentrum
8. Perfumemarket
9. Sabina

Scraper directories exist for all nine under `backend/scrapers/`.

## Integration status found in source

| Retailer | Scraper directory | Connector in `app.connectors` | Evidence / current status |
|---|---:|---:|---|
| Bplatz | yes | no dedicated adapter found | Scraper exists; not covered by legacy connector factory |
| Deloox | yes | yes, legacy wrapper | Included in `LegacyScraperConnector` factory |
| Easycosmetic | yes | yes, legacy wrapper | Included in `LegacyScraperConnector` factory |
| Notino | yes | yes, dedicated feed adapter | Authorized CJ/VIV XML feed adapter; separate runtime handlers exist |
| Orioudh | yes | no dedicated adapter found | Scraper exists; not covered by legacy connector factory |
| Parfumcity | yes | no dedicated adapter found | Scraper exists; not covered by legacy connector factory |
| Parfumzentrum | yes | yes, legacy wrapper | Included in `LegacyScraperConnector` factory |
| Perfumemarket | yes | no dedicated adapter found | Scraper exists; not covered by legacy connector factory |
| Sabina | yes | yes, legacy wrapper | Included in `LegacyScraperConnector` factory |

Important: a scraper directory is not proof that its scraper is currently healthy, compliant with retailer terms, or successfully ingesting products. Those require separate fixture and live-source checks.

## Shared connector contract already present

`backend/app/connectors/base.py` defines an async `StoreConnector` contract:
- `discover_products(cursor, limit)`
- `fetch_product(external_product_id)`
- `fetch_offers(product_key)`
- `fetch_price_and_stock(offer_id)`
- `parse_raw(raw)`
- shared validation for absolute HTTP(S) URL, positive finite price, ISO-like three-letter uppercase currency, and explicit in-stock/out-of-stock state.

The contract explicitly keeps network I/O out of user-facing search handlers and canonical database writes outside the connector.

## Existing integration evidence

- `legacy_scrapers.py` wraps exactly four retailers: Deloox, Sabina, Easycosmetic, Parfumzentrum.
- These wrappers require operator-configured discovery seed environment variables and fail closed when seeds are absent.
- `notino_feed.py` is a dedicated adapter for the authorized CJ/VIV XML feed. It caches a parsed feed snapshot and indexes records by external product ID.
- `connector_ingestion.py` provides shared staging, normalization, canonical matching and offer promotion.
- `connector_health.py` tracks failures and quarantines after five consecutive connector-wide outages, with explicit operator reinstatement.
- `notino_runtime.py` registers discovery, fetch and refresh handlers specifically for Notino. This is not evidence of a generic nine-retailer scheduler.

## Test coverage found

- Shared connector contract tests: present.
- Legacy connector tests: cover the four wrapped retailers through factory construction and fixture behavior.
- Notino feed tests: present, including Dior Sauvage EDP 100 ml fixture, stock-state validation, feed cache and missing-item behavior.
- Connector health tests: present.
- No equivalent dedicated connector contract/fixture test files were found for Bplatz, Orioudh, Parfumcity, or Perfumemarket in the inspected paths.

## Critical gap

The nine scraper implementations exist, but the provider-neutral connector layer currently exposes only five retailer adapters (four legacy wrappers + Notino). The remaining four scrapers are not yet registered behind the shared contract. Also, the live production SQLite snapshot had only one row in the `stores` table, Bplatz; this is database state, not the intended retailer scope.

## Safe next steps

1. Preserve all nine scraper implementations unchanged.
2. Build a source-level capability matrix for all nine (search/discovery, product-page parsing, price, currency provenance, stock, stable external ID, pagination/rate limits).
3. Add adapters for Bplatz, Orioudh, Parfumcity and Perfumemarket only after confirming their real function signatures and output fields.
4. Add fixture tests for every retailer: exact variant identity, size/concentration, price/currency provenance, in/out/unknown stock, malformed URL, timeout/blocked response, changed HTML/feed.
5. Create a generic retailer registry and worker orchestration; do not duplicate Notino-only runtime logic blindly.
6. Seed/verify all nine store records in a non-production database before any production migration.
7. Run each retailer independently with bounded concurrency, durable run records, retries, quarantine and dead-letter handling.

No scraper files were deleted or modified as part of this audit.
