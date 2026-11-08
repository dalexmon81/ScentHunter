# Maison Asrar official product-page provenance — fourth pass — 8 November 2026

## Scope

This pass links eight more existing Maison Asrar canonical identities to individual pages on the brand-owned storefront:

- Omniya
- Qamar
- Oh Honey!
- Patchouli with Love
- Pink Crush
- Oscar
- Petra
- Never Forget Me

No canonical identities or variants are added.

## Official product pages

| Existing identity | Official product page |
|---|---|
| Omniya | https://maisonasrar.com/products/omniya |
| Qamar | https://maisonasrar.com/products/qamar |
| Oh Honey! | https://maisonasrar.com/products/oh-honey-eau-de-parfum |
| Patchouli with Love | https://maisonasrar.com/products/patchouli-with-love-maison-asrar-eau-de-perfum-100-ml |
| Pink Crush | https://maisonasrar.com/products/maison-asrar-pink-crush-eau-de-parfum-100-ml-for-women |
| Oscar | https://maisonasrar.com/products/oscar-eau-de-perfum-100ml |
| Petra | https://maisonasrar.com/products/petra-maison-asrar-eau-de-perfum-100ml |
| Never Forget Me | https://maisonasrar.com/products/never-forget-me-maison-asrar-eau-de-perfum-90ml |

## Evidence boundaries

- All eight individual pages establish product names and Maison Asrar provenance.
- The Patchouli with Love page explicitly describes the product as Eau de Parfum, so the product concentration is recorded as `Eau de Parfum`.
- The retrieved page content does not explicitly expose a structured size field for any of these records.
- For the other seven products, EDP/size text present only in URL slugs is not promoted into structured attributes.
- No variants or formats are added.
- No prices, offers, stock, or availability are imported.

## Snapshot after this pass

- Canonical identities: 2,074 (unchanged)
- Total variants: 363 (unchanged)
- Maison Asrar identities: 120 (unchanged)
- Maison Asrar records with official individual product-page evidence: 37

## Regression protection

The existing `backend/tests/test_maison_asrar_official_product_pages.py` now validates these eight additional pages, records Patchouli with Love's explicitly stated concentration, and ensures unsupported sizes/concentrations are not inferred.
