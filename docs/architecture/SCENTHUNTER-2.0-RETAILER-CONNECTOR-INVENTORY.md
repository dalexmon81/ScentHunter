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


## Follow-up adapter compatibility audit (2026-11-21)

The four currently unwrapped scraper modules were reopened on the isolated branch and their public entry points inspected. This is a source-level audit only; no retailer requests were sent.

| Retailer | Discovery entry point | Product parser | Returned shape / identity concern | Adapter decision |
|---|---|---|---|---|
| Bplatz | `search_stream(query)` | `extract_product_page(session, url, query, html=None)` | One structured product mapping; SKU/GTIN are copied only from JSON-LD; currency is explicit only when JSON-LD `priceCurrency` exists; stock may remain unknown | Suitable for a dedicated adapter, but unknown stock and implicit EUR must remain unpublished |
| Orioudh | `search_stream(query)` | `extract_product_page(session, url, query="", html=None)` | Parser returns a list of Shopify variant records; each record contains product/variant identity and can have distinct price/stock | Must model each Shopify variant as a distinct retailer offer identity; do not collapse the list to its first item |
| Parfumcity | `search_stream(query)` | `product_json(session, url)` plus `make_item(product, variant, url, query)` | Shopify product JSON is expanded into variant rows; scraper currently labels currency EUR but does not prove currency provenance in the shared raw record | Adapter must mark currency as unverified unless source evidence is added; do not treat a hard-coded EUR default as explicit evidence |
| Perfumemarket | `search_stream(query)` | `extract_product_page(session, url, query)` | Product-page parser returns a mapping; availability deliberately returns `unknown` when stock evidence is insufficient; currency provenance needs explicit inspection of the returned fields | Dedicated adapter is possible, but unknown availability must fail the active-offer gate |

### Implementation constraints confirmed

- The current `LegacyScraperConnector` assumes `extract_product_page` returns one mapping and dispatches only the four configured legacy modules. It is not a safe drop-in wrapper for Orioudh's list-of-variants parser.
- Discovery uses operator-provided query seeds. The new adapters must preserve that fail-closed behavior; no broad discovery should run merely because a worker starts.
- Stable product URL and stable variant ID are different concepts. Where a source exposes Shopify variant IDs, the offer identity must include the variant ID. Reusing only the product URL would merge distinct sizes/prices into one offer.
- A scraper's EUR default is not proof that the retailer explicitly supplied EUR. The shared promotion gate requires explicit currency evidence, so adapters must preserve provenance rather than manufacture it.
- `unknown` stock is not equivalent to `in_stock`. Keep it staged/unpublished until the retailer provides a positive or negative stock signal.
- Existing parser functions differ in whether they accept a prebuilt session, perform their own network request, return one mapping, or return a list. The adapter layer must normalize these differences intentionally and close sessions reliably.

### Next safe implementation order

1. Add fixture-driven contract tests for the four modules before writing adapters. Cover multiple variants, distinct prices, missing currency, unknown stock, parser empty results, timeout/blocked responses, and duplicate product URLs.
2. Implement Bplatz and Perfumemarket as mapping-based adapters with strict explicit-currency and availability handling. (Adapter code and fixture tests are now present on the isolated branch; CI verification is pending. PerfumeMarket currency provenance is intentionally fail-closed because the current scraper output does not expose source-level currency evidence.)
3. Implement Parfumcity and Orioudh as variant-aware adapters. Give each offer a stable external identity derived from retailer product ID plus retailer variant ID; never use array position.
4. Add all four to a registry only after the contract tests pass.
5. Run the isolated PostgreSQL persistence tests against these fixture records. No live ingestion, production DB, worker activation, merge, or deployment is part of this phase.

No scraper code or production configuration was changed in this follow-up audit.


## Adapter implementation progress (2026-11-21)

- Added `backend/app/connectors/bplatz.py` and fixture tests. The adapter reuses
  the existing parser, uses product URLs as stable IDs, and preserves unknown
  stock and implicit currency as non-publishable states.
- Added `backend/app/connectors/perfumemarket.py` and fixture tests. Its
  discovery rejects unverified empty reports. Currency remains unverified
  unless the scraper explicitly supplies provenance; current scraper output
  does not, so normal records cannot pass the promotion currency gate.
- Both adapters are exported from `app.connectors`, but are not connected to
  `legacy_runtime`, scheduler dispatch, or an active retailer registry.
- CI workflow now includes both adapter test modules. The new workflow run
  has not yet been inspected, so test success is not claimed.
- No retailer HTTP calls, production database writes, worker activation,
  merge, or deployment were performed.
