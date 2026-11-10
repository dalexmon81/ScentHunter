# Maison Asrar official New Arrivals cross-check — 10 November 2026

## Scope

The official Maison Asrar New Arrivals collection currently exposes 12 named fragrance entries. Each collection link was followed to its individual Maison Asrar product page and compared with the canonical product seed.

## Reconciliation result

All 12 collection entries already have exactly one canonical identity in the catalog, each with `source_verified_name` status and the matching individual official product URL:

- Ameer — https://maisonasrar.com/products/ameer
- Belgravia — https://maisonasrar.com/products/belgravia
- DXB Jumeirah — https://maisonasrar.com/products/dxb-jumeirah
- Last Swim — https://maisonasrar.com/products/last-swim
- Silent Surge — https://maisonasrar.com/products/silent-surge
- Regent — https://maisonasrar.com/products/regent
- Veyra — https://maisonasrar.com/products/veyra
- Infina — https://maisonasrar.com/products/infina
- Librae — https://maisonasrar.com/products/librae
- Harmony — https://maisonasrar.com/products/harmony
- Fairyland — https://maisonasrar.com/products/fairyland
- Whisper — https://maisonasrar.com/products/whisper

No new product identity was added in this pass because all twelve were already represented. No concentration or bottle size was inferred from the collection listing; only fields explicitly supported by the individual product data should be used to create variants.

## Exclusions and limits

- The official site navigation separates fragrances from room sprays and home fragrances. Non-perfume categories are not added as fragrance identities.
- The New Arrivals page displays 12 collection entries in the retrieved page content, while the catalog contains a broader Maison Asrar set. This is not an exhaustive audit of every Maison Asrar historical or current product.
- No prices, stock levels, availability, or retailer offers were copied into the canonical catalog.

## Automated protection

`backend/tests/test_maison_asrar_new_arrivals_2026_11_10.py` asserts unique canonical identities, official product-page provenance, and basic category hygiene for these twelve entries.

## CI trigger

The parent catalog-validation workflow now explicitly includes `catalog/gulf-orchid-new-arrivals-2026-11-10` as an allowed pull-request target branch, so this stacked audit PR is covered by the same catalog validation workflow.
