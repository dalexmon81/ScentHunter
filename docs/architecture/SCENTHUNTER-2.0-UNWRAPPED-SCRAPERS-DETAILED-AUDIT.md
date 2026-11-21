# ScentHunter 2.0 — Detailed audit of the four unwrapped retailer scrapers

Audit date: 2026-11-21
Source inspected: `main`, files under `backend/scrapers/`.
Scope: read-only source inspection. No retailer network calls were made. No scraper implementation was changed.

## Executive result

The four scrapers are not interchangeable. All expose `search_stream`, but their product hydration and output schemas differ. They should be integrated through small retailer-specific adapters over the existing parsers, not by forcing them into the existing four-store legacy factory.

| Retailer | Discovery entry point | Product parser | Output characteristics | Key integration concern |
|---|---|---|---|---|
| Bplatz | `search_stream(query)` | `extract_product_page(session,url,query,html=None)` | Nested `source`, `identity`, `attributes`, `offer`, `provenance`; product URL used as external ID by discovery | Discovery results are already product-page parsed; parser returns one nested record; explicit currency comes from Product JSON-LD |
| Orioudh | `search_stream(query)` | `extract_product_page(session,url,query,html=None)` | Shopify variant records; nested identity/attributes/offer; variant IDs and GTIN/barcode can be present | Parser returns a list of variant offers; currency is currently set to EUR in source output, so provenance must be checked before treating it as explicit |
| Parfumcity | `search_stream(query)` | `product_json(session,url)` and `make_item(product,variant,url,query)` | Shopify variant records; nested identity/attributes/offer; store product and variant IDs; SKU if present | Currency is set to EUR in generated offer; no explicit source-currency evidence is carried in the shown normalized output |
| Perfumemarket | `search_stream(query)` | `extract_product_page(session,url,query)` | Flat record: name, brand, URL, SKU/GTIN/MPN, price, currency, availability; JSON-LD first with HTML fallbacks | Currency defaults to EUR if missing; availability can be `preorder`; parser prints errors and does not consistently close response on every early return |

## Detailed notes

### Bplatz

- Uses a generic multi-channel discovery strategy: Shopify predictive search, Shopify search, product catalog JSON and sitemap fallback.
- Bounds candidate count and catalog pages.
- `search_stream` returns a structured report with status, verification flag, results and details.
- Product parser reads Product JSON-LD for SKU/GTIN and offer price/currency/availability, with page text fallback for price and stock.
- Returns nested evidence and identity fields. Product URL is a safe external reference, but not a retailer-native immutable SKU.
- Request timeout is bounded at connect/read tuple (2.5, 6 seconds).
- Important: adapter should preserve `currency_explicit` only when Product JSON-LD supplied `priceCurrency`; never infer it merely from EUR-looking price text.

### Orioudh

- Shopify predictive search discovery with broader query fallbacks and rendered search fallback.
- Product source is Shopify `.js` JSON.
- Parser returns a list because a product can have multiple variants.
- Has Shopify product ID, variant ID, SKU and barcode/GTIN provenance.
- Availability derives from each variant's boolean `available`.
- Price parser treats numeric Shopify prices as integer cents.
- The output currently declares EUR in its offer mapping. The inspected code does not establish that this value was read from the retailer response. Treat currency provenance as unverified until fixture/source verification; do not mark it explicit solely because the field is populated.

### Parfumcity

- Shopify catalog JSON and sitemap discovery fallbacks; bounded candidates/pages.
- Product JSON is fetched and each Shopify variant is parsed separately.
- Emits store product ID, variant ID and SKU when present.
- Availability comes from the variant's boolean `available`; unknown remains unknown.
- Generated offer currency is EUR, but the inspected item builder does not show a source-derived currency field. Must be treated as configured/store-market currency, not explicit offer evidence, unless separately verified.
- Existing parser returns a structured search report and preserves discovery/fetch errors.

### Perfumemarket

- Multi-channel discovery across predictive search, catalog and sitemap paths.
- `search_stream` deliberately marks empty results unverified; this must not be converted into a definitive NOT_FOUND.
- Product-page parser prefers JSON-LD then product-bound HTML fields.
- Flat record includes identity values and offer values.
- Currency currently falls back to EUR if JSON-LD does not provide a currency. The adapter must distinguish source-provided currency from this fallback.
- Availability supports `preorder` as a distinct state; the common publication contract accepts only `in_stock` and `out_of_stock`. Preserve preorder as non-publishable/needs-policy-review, not as in-stock.
- Parser uses diagnostic `print` calls for some request failures; these should be routed through structured logging in a later cleanup, not silently suppressed.
- Response closure should be checked/fixed in the adapter/parser boundary before high-volume worker use.

## Integration design decision

Do not add these four to `LegacyScraperConnector` as-is. That class assumes:
- discovery results contain a usable URL in a small set of flat keys;
- product fetch returns one mapping;
- parsing can normalize the legacy flat keys.

Those assumptions do not cover the nested Shopify variant records and list-returning Orioudh parser safely.

Recommended implementation:
1. Add a small adapter module for Bplatz, Orioudh, Parfumcity and Perfumemarket, retaining each existing scraper as the source of truth.
2. Each adapter must map one retailer's parsed product/variant record into one or more normalized offer candidates.
3. Use stable external IDs: retailer variant ID when available; otherwise retailer product ID; URL only as a documented fallback. Never use a guessed SKU/GTIN.
4. Carry currency provenance separately from currency value. Store-configured EUR is not equivalent to source-explicit EUR.
5. Keep `unknown` stock and `preorder` distinct. Do not publish either as `in_stock`.
6. Keep discovery status/verification metadata. Empty unverified results must be recorded as partial/error, never NOT_FOUND.
7. Add fixture tests per retailer before enabling scheduled ingestion.

## Required fixture cases before activation

- Dior Sauvage EDP 100 ml exact variant and a different size from the same product page.
- Product with no GTIN and no SKU.
- Explicit in-stock, out-of-stock, unknown and (where applicable) preorder.
- Currency explicitly present and currency missing/defaulted.
- Price missing, zero, malformed and locale-formatted.
- Discovery returns verified empty vs unverified empty.
- Timeout, 403/429, 5xx, invalid JSON and changed product-page markup.
- Duplicate discovery URLs and duplicate product variants.

## What is not proven by this audit

- Current retailer accessibility or permission/terms for each access method.
- Live success rates, freshness, stock accuracy or price accuracy.
- Whether all parser output paths are covered by existing tests.
- Whether the four scrapers can sustain scheduled concurrency without rate limiting.
- Production ingestion success for any of these four retailers.

No production state was changed and no scraper code was edited.
