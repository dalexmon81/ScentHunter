# Zimaya product-detail verification — 2026-11-08

Official source: https://zimayaperfumes.com/collections/all

The canonical seed already contained 70 Zimaya collection-listed identities. This update verified ten existing names against individual official product-detail pages and created 100 ml Eau de Parfum variant rows for them. Two missing names were added as new canonical identities and synchronized into `backend/family_registry.json`.

## Product-detail evidence

| Canonical name | Official page | Explicit detail |
|---|---|---|
| Cult | https://zimayaperfumes.com/products/cult | 100 ml, EDP, Unisex |
| Exquisite | https://zimayaperfumes.com/products/exquisite | 100 ml, EDP, Pour Femme |
| Sharaf Blend | https://zimayaperfumes.com/products/sharaf-blend-100ml | 100 ml, EDP, Unisex |
| Grandeur | https://zimayaperfumes.com/products/grandeur-100ml | 100 ml, EDP, Unisex |
| Crysta Oud | https://zimayaperfumes.com/products/crysta-oud-100ml | 100 ml, EDP, Unisex |
| Farah | https://zimayaperfumes.com/products/farah | 100 ml, EDP, Pour Femme |
| Amber Is Great | https://zimayaperfumes.com/products/amber-is-great-100ml | 100 ml, EDP, Pour Homme |
| Bahjah | https://zimayaperfumes.com/products/bahja | 100 ml, EDP, Pour Femme |
| Wujood | https://zimayaperfumes.com/products/wujood-100ml | 100 ml, EDP, Pour Homme |
| Luxor | https://zimayaperfumes.com/products/luxor-100ml | 100 ml, EDP, Pour Femme |

## Changes

- 8 existing identities promoted to `source_verified_name`, with explicit EDP concentration and official product URLs.
- Added Wujood and Luxor as canonical identities (the names were absent from the prior 70-record Zimaya set).
- Added 10 corresponding 100 ml EDP variant rows.
- Added Wujood and Luxor to the Zimaya family registry.
- No prices, stock, retailer offers, GTINs, MPNs, shipping values or image URLs were invented.

## Structural audit after update

- 1,721 canonical identities.
- 180 explicit variant rows.
- 72 Zimaya identities in the current seed.
- 10 Zimaya 100 ml EDP variant rows from product-detail evidence.
- 0 duplicate product IDs.
- 0 duplicate variant IDs.
- 0 orphan variant references.

The catalogue remains a discovery/canonical identity seed. This verification does not claim that all 104 products in the official Zimaya collection have been imported or that every other requested brand is exhaustive. The change is on the draft catalog-expansion PR branch only; `main` and production remain unchanged.


## Additional official product-detail batch — 2026-11-10

Four existing Zimaya identities were verified against their individual first-party product pages:

| Canonical name | Official product page | Explicit detail |
|---|---|---|
| Abadi Opulent | https://zimayaperfumes.com/products/abadi-opulent-edp-100ml | 100 ml, EDP, Pour Homme |
| Abadi Saga | https://zimayaperfumes.com/products/abadi-saga-pour-homme-edp-100ml | 100 ml, EDP, Pour Homme |
| Al Barari Coral | https://zimayaperfumes.com/products/al-barari-coral | 100 ml, EDP, Unisex |
| Al Barari Shore | https://zimayaperfumes.com/products/al-barari-shore | 100 ml, EDP, Pour Homme |

- Reused all four existing canonical product IDs.
- Added four 100 ml Eau de Parfum variants and synchronized parent formats in the family registry.
- No GTIN was visible on the inspected official product detail pages; none was inferred.
- No prices, stock, availability, retailer offers or shipping data were added.


## Additional official product-detail batch — 2026-11-10 (Europe storefront)

Three existing Zimaya canonical identities were checked against their individual official European product pages:

| Canonical name | Official product page | Explicit detail |
|---|---|---|
| Afrah | https://fr.zimayaperfumes.com/products/afrah | 20 ml, concentrated perfume oil (CPO), Unisex |
| Al Embratur Elixir | https://fr.zimayaperfumes.com/products/al-embratur-elixir | 100 ml, EDP, Pour Homme |
| Ghali Imperial | https://fr.zimayaperfumes.com/products/ghali-imperial | 100 ml, EDP, Pour Homme |

- Reused the three existing canonical product IDs; no new identities were created.
- Added two 100 ml EDP variants and one 20 ml concentrated-oil variant.
- Updated product-level format/concentration fields and the matching Zimaya family-registry formats.
- Afrah is a concentrated perfume oil, not an EDP; its 20 ml CPO variant is represented separately.
- No GTIN, SKU, retailer offer, stock or shipping data was inferred.
