# Al Wataniah cumulative official catalog reconciliation — 10 November 2026

## Current cumulative snapshot

The current cumulative catalog branch (PR #715, based on the verified #714 line) retains all 86 canonical Al Wataniah identities and now has individual official product-page evidence for all 86.

- **86 canonical identities** retained; no new canonical products were created in this reconciliation.
- **84 explicit variants**, each supported by an individual official product page specifying **100 ml Eau de Parfum**.
- **2 identity-only products** — House Of Oud and Anwan — remain without a variant because the accessible official pages do not establish size and concentration.
- **0 listing-only identities** remain: Rawaee Noble, Rawaee Regina and Redaa were subsequently verified against individual official product pages.
- The family registry is synchronized with the 84 explicit 100 ml formats and preserves the existing canonical identities and aliases.

The 84 variants comprise the earlier 81-variant reconciliation plus three later verified variants:

- Rawaee Noble — https://www.alwataniah.com/products/rawaee-noble
- Rawaee Regina — https://www.alwataniah.com/products/rawaee-regina
- Redaa — https://www.alwataniah.com/products/redaa

Each of these three official pages explicitly states Type: Eau de Parfum and Volume: 100 ML. Their product IDs are reused; one 100 ml Eau de Parfum variant is present for each.

## Historical integration accounting

The earlier cumulative integration added 79 new variant records and enriched two existing variant records with official product-page provenance, bringing that checkpoint to 81 explicit variants. The subsequent Rawaee Noble, Rawaee Regina and Redaa detail-page follow-up added three more variants, bringing the current cumulative total to 84.

## Data safety

- No price, currency, stock, availability, shipping, retailer or affiliate data is stored in canonical products or variants.
- No GTIN or MPN is inferred.
- No size or concentration is inferred from a product name, image, collection listing or URL slug.
- House Of Oud and Anwan remain identity-only until official evidence explicitly establishes size and concentration.
- Existing product and variant IDs are preserved.

## Regression coverage

The catalog seed workflow now invokes all Al Wataniah evidence suites:

- `backend.tests.test_al_wataniah_detail_evidence` — validates the earlier 81 explicit variants and the two identity-only official pages.
- `backend.tests.test_al_wataniah_official_collection_harvest` — validates all 86 collection identities and the complete 84-variant detail set.
- `backend.tests.test_al_wataniah_official_storefront` — protects the earlier individual product-page provenance.
- `backend.tests.test_al_wataniah_official_details_2026_11_10` — validates the three later product pages and their variants.
- `backend.tests.test_al_wataniah_cumulative_coverage_2026_11_10` — asserts the current 86 / 84 / 2 cumulative coverage and registry alignment.

The exact PR head must pass the catalog seed workflow before this follow-up is considered validated.
