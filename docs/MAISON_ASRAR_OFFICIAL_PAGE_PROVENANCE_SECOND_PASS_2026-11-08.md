# Maison Asrar official product-page provenance — second pass — 8 November 2026

## Scope

This pass links six existing Maison Asrar canonical identities to individual pages on the brand-owned Maison Asrar storefront:

- Vanilla Aura
- Faris Al Arab
- III Thriller
- Muharib
- Hunter
- 1963

No canonical identities or variants are added. The catalog records gain official detail-page provenance and `source_verified_name` status.

## Official product pages

| Existing identity | Official product page |
|---|---|
| Vanilla Aura | https://maisonasrar.com/products/vanilla-aura |
| Faris Al Arab | https://maisonasrar.com/products/faris-al-arab |
| III Thriller | https://maisonasrar.com/products/iii-thriller |
| Muharib | https://maisonasrar.com/products/muharib |
| Hunter | https://maisonasrar.com/products/maison-asrar-hunter-eau-de-parfum-100ml |
| 1963 | https://maisonasrar.com/products/1963-eau-de-perfum-100ml |

## Evidence boundaries

- The pages establish the individual product names and brand-owned provenance.
- The retrieved page content does not explicitly show a size or concentration field for these six records.
- Although the Hunter and 1963 URL slugs contain size/concentration wording, the catalog does not promote those strings into structured attributes without explicit product-page detail.
- No variants, formats, or concentrations are added.
- No prices, stock, retailer offers, or availability are imported.

## Snapshot after this pass

- Canonical identities: 2,074 (unchanged)
- Total variants: 363 (unchanged)
- Maison Asrar identities: 120 (unchanged)
- Maison Asrar records with official individual product-page evidence: 24

## Regression protection

The existing `backend/tests/test_maison_asrar_official_product_pages.py` now checks these six pages as well as the earlier six records, including the rule that no unsupported size or concentration is invented.
