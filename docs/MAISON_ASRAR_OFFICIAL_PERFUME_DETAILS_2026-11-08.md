# Maison Asrar official perfume detail reconciliation — 2026-11-08

## Source scope and count discrepancy
The brand's official all-products collection currently displays 130 products, while its dedicated Fragrances collection displays 74 products. The latter is the relevant collection for perfume-catalog scope; the general store includes separate Room Spray and Home Fragrances navigation categories. Counts are storefront counts and may change.

Sources:
- https://maisonasrar.com/collections/all
- https://maisonasrar.com/collections/perfume-sprays

The existing ScentHunter catalog contains 120 Maison Asrar identities. This PR does not assume those 120 are all current fragrances and does not delete or add identities based on storefront counts alone.

## Verified official detail pages
Twelve existing identities are upgraded from collection-level listing evidence to official individual product pages:
- Bloom Bloom — 100 ml Eau de Parfum
- Lolita — 100 ml Eau de Parfum
- Bonita — 100 ml Eau de Parfum
- Lily — 100 ml Eau de Parfum
- Kiss My Lips — 90 ml Eau de Parfum
- Never Forget Me — 90 ml Eau de Parfum
- Night in Paris — 90 ml Eau de Parfum
- Sunset in Capri — 90 ml Eau de Parfum
- Dear Jasmine — 100 ml Eau de Parfum
- Patchouli with Love — 100 ml Eau de Parfum
- Fresh Iris — 100 ml Eau de Parfum
- Vanilla Rouge — 100 ml Eau de Parfum

Each product receives an individual official URL and one variant with the exact size shown in the official product-page URL/title. Existing product IDs are preserved.

## Catalog impact
- Canonical identities: unchanged.
- Explicit variants: +12.
- No prices, stock, availability, shipping or retailer offers added.
- No room sprays or home-fragrance products introduced.

## Follow-up audit
The remaining Maison Asrar identities require a full paginated reconciliation against the official Fragrances collection. A general collection count is not a valid proxy for perfume identity coverage.
