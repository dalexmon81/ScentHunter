# Bujairami UAE official detail-page evidence — 8 November 2026

## Scope

This batch upgrades ten existing Bujairami catalog identities from a UAE collection-listing URL to individual product pages on the brand-owned UAE storefront.

| Existing canonical identity | Official product page |
|---|---|
| Absolute Power | https://bujairami.ae/products/absolute-power-inspired-by-le-male-elixir-absolu-jean-paul-gaultier |
| ACE | https://bujairami.ae/products/ace-inspired-by-uomo-born-in-roma-coral-fantasy-valentino |
| Agha | https://bujairami.ae/products/agha-inspired-by-althair-from-parfums-de-marly |
| Apex | https://bujairami.ae/products/apex-inspired-by-amiri-arabian-oud-extrait |
| Blush | https://bujairami.ae/products/blush-inspired-by-good-girl-blush-carolina-herrera |
| Booz Extreme | https://bujairami.ae/products/booz-extreme |
| Boss Life | https://bujairami.ae/products/boss-life-inspired-by-outlands-from-amouage |
| Boujee | https://bujairami.ae/products/boujee-inspired-by-attrape-reves-from-louis-vuitton |
| Candy Carousel | https://bujairami.ae/products/candy-carousel-inspired-by-l-eau-de-parfum-from-cirque-du-soleil |
| Dubai Crush | https://bujairami.ae/products/dubai-crush-original-creation |

The pages cover both inspired fragrances and the existing original creation Dubai Crush. This classification follows the official product-page titles; it does not create new catalog identities.

## Catalog changes

- Upgrades ten existing records to `identity_status: source_verified_name`.
- Sets `source_url` and `source_evidence_url` to the corresponding individual product page.
- Preserves canonical product IDs, names, aliases, and family assignment.
- Adds no canonical identities or variants.
- Adds no concentration or size fields. Although the Agha page visibly offers a 100 ml option, this batch intentionally does not infer or add a variant.
- Imports no price, stock, availability, shipping, or retailer-offer data.

## Cumulative snapshot

- Total canonical products: 2,743
- Total variants: 717
- Bujairami identities: 671
- Bujairami identities with individual detail-page evidence: 47
- Bujairami variants: 8

## Regression protection

`backend.tests.test_bujairami_uae_detail_evidence` verifies the ten first-party URLs, preserved identity counts, absence of inferred size/concentration, and unchanged variant totals.
