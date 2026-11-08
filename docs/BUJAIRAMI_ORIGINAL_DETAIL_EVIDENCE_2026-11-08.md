# Bujairami original-creation detail evidence — 8 November 2026

## Scope

This change upgrades four existing Bujairami canonical identities from regional collection/listing provenance to individual product-page evidence on the brand-owned Australian storefront.

The official Australian Originals collection lists these names as Bujairami original creations. Each corresponding product page independently confirms the product title and fragrance details:

| Existing canonical identity | Official product page |
|---|---|
| Ruthless Vanilla | https://bujairami.com.au/products/ruthless-vanilla-original-creation |
| The Aftermath | https://bujairami.com.au/products/the-aftermath-by-bujairami-for-men-original-creation |
| Her | https://bujairami.com.au/products/her |
| Mohabbat | https://bujairami.com.au/products/mohabbat-original-creation |

## Catalog changes

- Upgrades four existing product records to `identity_status: source_verified_name`.
- Sets `source_url` and `source_evidence_url` to each product's individual official page.
- Preserves all existing product IDs, canonical names, aliases, and family-registry entries.
- Adds no canonical identities and no variants.
- Adds no sizes or concentrations: the inspected page evidence used for this change does not establish a product-specific size/concentration pair suitable for catalog promotion.
- Imports no price, stock, availability, shipping, or retailer-offer data.

## Cumulative snapshot

- Total canonical products: 2,743
- Total variants: 717
- Bujairami identities: 671
- Bujairami identities with individual detail evidence: 37
- Bujairami variants: 8
- No duplicate identities or variant rows introduced.

## Regression protection

`backend/tests/test_bujairami_original_detail_evidence.py` verifies the four individual source URLs, the evidence status, preserved identity count, absence of inferred size/concentration, and unchanged Bujairami variant count.
