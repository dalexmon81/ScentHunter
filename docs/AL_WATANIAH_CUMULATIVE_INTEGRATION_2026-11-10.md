# Al Wataniah cumulative official-detail integration — 10 November 2026

## Integrated result

The previously CI-validated Al Wataniah official-detail work from the November 9 evidence branches has been reconciled onto the current cumulative catalog head. Existing canonical product IDs are preserved; no new canonical identities are created.

- 86 existing Al Wataniah canonical identities retained.
- 83 identities have individual official product-detail evidence.
- 81 variants are supported by individual official pages, each explicitly specifying 100 ml Eau de Parfum.
- House Of Oud and Anwan remain identity-only: the inspected official pages identify the fragrances but do not explicitly state size and concentration.
- Rawaee Noble, Rawaee Regina and Redaa remain collection-listed because their individual detail URLs were unavailable during the prior audit.
- 79 new variant records are added; the two existing variant records are enriched with official evidence URLs.
- The family registry is synchronized, including the additional official alias for Da'im.

## Data safety

No price, currency, stock, availability, shipping, retailer, GTIN, MPN or affiliate data is inferred or imported. No size or concentration is inferred from product names or URL slugs. No product or variant identity collisions were found against the current cumulative catalog.

## Regression coverage

The current catalog validation workflow invokes:
- `backend.tests.test_al_wataniah_detail_evidence` — verifies the 81 explicit variants and two identity-only pages.
- `backend.tests.test_al_wataniah_official_collection_harvest` — verifies all 86 collection identities, explicit variants, and three unresolved listing-only records.
- `backend.tests.test_al_wataniah_official_storefront` — preserves the previously reconciled individual official page URLs.

The first two regression modules are updated to the full previously validated evidence set.

## Provenance

This integration carries forward the product-page evidence and regression coverage from the existing draft Al Wataniah work, including PR #618, but is rebased onto the current cumulative catalog branch. The original draft PRs remain open and untouched.
