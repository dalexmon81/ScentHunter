# Maison Asrar official product-page provenance — third pass — 8 November 2026

## Scope

This pass links five more existing Maison Asrar canonical identities to individual pages on the brand-owned storefront:

- Lumiere
- Milky Way
- Mohra
- Luna
- Magic Night

No canonical identities or variants are added. The five existing records gain official product-page provenance and `source_verified_name` status.

## Official product pages

| Existing identity | Official product page |
|---|---|
| Lumiere | https://maisonasrar.com/products/lumiere |
| Milky Way | https://maisonasrar.com/products/milky-way |
| Mohra | https://maisonasrar.com/products/mohrab |
| Luna | https://maisonasrar.com/products/luna-eau-de-parfum-100ml |
| Magic Night | https://maisonasrar.com/products/magic-night-eau-de-perfum-100ml |

## Evidence boundaries

- The official pages establish the individual product names and Maison Asrar provenance.
- The retrieved page content does not explicitly provide structured size or concentration fields for these five records.
- Size/concentration wording embedded in URL slugs is not promoted into structured attributes.
- No variants, formats, or concentrations are added.
- The similarly named Masterpiece page was not included: its product slug identifies it as Gulf Orchid Masterpiece, so it is not silently attributed to Maison Asrar's canonical brand set.

## Snapshot after this pass

- Canonical identities: 2,074 (unchanged)
- Total variants: 363 (unchanged)
- Maison Asrar identities: 120 (unchanged)
- Maison Asrar records with official individual product-page evidence: 29

## Regression protection

The existing `backend/tests/test_maison_asrar_official_product_pages.py` now checks these five pages as well as the previous twelve, including the rule that no unsupported size or concentration is inferred.
