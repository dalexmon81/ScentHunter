# Maison Asrar official-page reconciliation — 8 November 2026

## Scope

This is a provenance reconciliation, not a full catalog expansion. The Maison Asrar slice contains 120 canonical identities in the current catalog snapshot. No identities are added or removed by this change.

The brand-owned storefront currently exposes:
- an all-products collection showing 130 products, which includes fragrance and home-fragrance categories;
- a dedicated Fragrances collection showing 74 products;
- a separate Royal Collection with 9 products.

These counts describe different Shopify collections and must not be added together or interpreted as canonical perfume identity totals.

## Official individual pages attached

Six existing catalog identities previously supported only by a collection listing or an external guide now point to individual brand-owned product pages:

| Canonical identity | Official page |
|---|---|
| Ameer | https://maisonasrar.com/products/ameer |
| Veyra | https://maisonasrar.com/products/veyra |
| Vanilla Voyage | https://maisonasrar.com/products/vanilla-voyage-eau-de-parfum |
| Last Swim | https://maisonasrar.com/products/last-swim |
| Silent Surge | https://maisonasrar.com/products/silent-surge |
| DXB Jumeirah | https://maisonasrar.com/products/dxb-jumeirah |

For these six records:
- `source_url` and `source_evidence_url` now point to the individual brand-owned page;
- `identity_status` is upgraded to `source_verified_name`;
- no `formats_ml`, concentration, or variant has been added because the inspected page content does not explicitly establish those attributes.

## Reconciliation observations

- The official Fragrances collection reports 74 products. The paginated web extraction exposed repeated product cards across pages; therefore its observed unique-name subset is not treated as a complete, exact 74-name export.
- Every distinct name captured in the official collection page excerpts matched an existing Maison Asrar canonical identity in this catalog snapshot. No additional canonical product was created from those excerpts.
- The official Royal Collection is a separate collection. Its nine entries are covered by the existing `test_maison_asrar_royal_collection.py` regression test.
- The brand's all-products collection includes non-perfume home-fragrance categories. Those must not be imported as wearable perfume identities.
- Three records currently carry Gulf Orchid retailer URLs rather than Maison Asrar brand-owned pages: Plot Twist, Love Key, and Unsolved Mystery. They remain explicitly separate evidence cases and are not upgraded to manufacturer-verified records here.
- An independent EU guide reports 116 scent entries and explicitly says it is unofficial and includes two entries not shown on the brand's website. This is useful discovery context only, not a substitute for brand-owned product evidence.

## Guardrails

- No price, stock, retailer offer, or shipping data is copied into the canonical catalog.
- No size or concentration is inferred from a collection listing, reseller page, or product name.
- No existing product is deleted just because it is absent from the current Fragrances collection; absence may reflect collection membership, regional presentation, or discontinued/legacy status.
- Future reconciliation should check individual brand-owned product pages and the specific collection context before changing canonical identity status.

## Regression protection

`backend/tests/test_maison_asrar_official_product_pages.py` checks the six official detail-page URLs and ensures no unsupported size/concentration fields were introduced.
