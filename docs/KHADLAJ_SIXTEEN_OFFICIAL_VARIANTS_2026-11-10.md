# Khadlaj official product-page reconciliation — 10 November 2026

## Result

Sixteen existing Khadlaj canonical identities were reconciled against individual official product pages. Sixteen explicit size/concentration variants were added; no new product identities were created.

| Product | Size | Concentration | GTIN |
|---|---:|---|---|
| Hareem Al Sultan | 75 ml | Eau de Parfum | 6291107976556 |
| Azure Velvet | 100 ml | Extrait de Parfum | 6291107978802 |
| Le Prestige King | 100 ml | Eau de Parfum | 6291107975955 |
| The Proposal Date Night | 100 ml | Eau de Parfum | 6291197975818 |
| The Proposal Special Occasion | 100 ml | Eau de Parfum | Not recorded; official page's displayed SKU is not a valid 13-digit GTIN |
| 25 Experience | 100 ml | Eau de Parfum | 6291107975351 |
| 25 Trust | 100 ml | Eau de Parfum | 6291107975399 |
| 25 Loyalty | 100 ml | Eau de Parfum | 6291107975382 |
| 25 Heritage | 100 ml | Eau de Parfum | 6291107975368 |
| 25 Integrity | 100 ml | Eau de Parfum | 6291107975375 |
| Karus Amber Gold | 100 ml | Eau de Parfum | 6291107975849 |
| Maison Creation De Reve | 100 ml | Eau de Parfum | 6291107976037 |
| Maison Epoque Artistique | 100 ml | Eau de Parfum | Not recorded; official page's displayed SKU is not a valid 13-digit GTIN |
| Maison L'Or Noir | 100 ml | Eau de Parfum | 6291107976020 |
| Maison Flor Oud | 100 ml | Eau de Parfum | 6291107976068 |
| Mystical Indian Oud Pure | 60 ml | Eau de Parfum | 6291107974613 |

## First-party evidence

- Hareem Al Sultan: https://khadlaj-perfumes.com/collections/unisex-1/products/tiktk-viral-hareem-al-sultan-perfume-in-75-ml-edp-spray-by-khadlaj-dubai
- Azure Velvet: https://khadlaj-perfumes.com/collections/unisex-1/products/azure-velvet-100-ml-extrait-de-parfum-unisex-fragrance-to-buy-online-dubai-uae
- Le Prestige King: https://khadlaj-perfumes.com/collections/unisex-1/products/le-prestige-king-100-ml-edp-spray
- The Proposal Date Night: https://khadlaj-perfumes.com/products/the-proposal-date-night-100-ml-edp-spray
- The Proposal Special Occasion: https://khadlaj-perfumes.com/collections/women-perfume/products/the-proposal-special-occasion-100-ml-edp-spray
- 25 Experience: https://khadlaj-perfumes.com/collections/khadlaj-25-eau-de-parfum-collection/products/khadlaj-25-experience-100-ml-edp-spray
- 25 Trust: https://khadlaj-perfumes.com/products/buy-khadlaj-25-trust-100-ml-edp-spray-best-gourmand-perfume-for-women
- 25 Loyalty: https://khadlaj-perfumes.com/products/khadlaj-25-loyalty-100-ml-edp-spray-best-women-perfume-to-shop-online-dubai-uae
- 25 Heritage: https://khadlaj-perfumes.com/products/khadlaj-25-heritage-100-ml-edp-spray
- 25 Integrity: https://khadlaj-perfumes.com/collections/unisex-1/products/khadlaj-25-integrity-100-ml-edp-spray
- Karus Amber Gold: https://khadlaj-perfumes.com/products/karus-amber-gold-100-ml-edp-spray
- Maison Creation De Reve: https://khadlaj-perfumes.com/products/maison-creation-de-reve-100ml
- Maison Epoque Artistique: https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/maison-epoque-artistique-100ml-edp-spray
- Maison L'Or Noir: https://khadlaj-perfumes.com/products/maison-l-or-noir-100ml-edp-spray
- Maison Flor Oud: https://khadlaj-perfumes.com/products/maison-flor-oud-100ml-edp-spray
- Mystical Indian Oud Pure: https://khadlaj-perfumes.com/products/mystical-indian-oud-pure-60-ml-edp-spray

The official product pages identify the size and concentration shown in the table. The Proposal Special Occasion page displays a 12-digit SKU; it is not copied into the GTIN field. Maison Epoque Artistique has no numeric product identifier in the inspected page result, so no GTIN is recorded.

## Catalog changes

- Reused the sixteen existing canonical product IDs.
- Upgraded product identity status and stored individual official product-page provenance.
- Added one explicit variant per existing product with the documented size and concentration.
- Added GTINs only when the official page exposed a numeric identifier; no identifier was inferred.
- Updated the existing `khadlaj_official_perfume_sprays_2026_11` family-registry rows.
- No product identities were duplicated and no existing variants were overwritten.

No price, stock, availability, shipping, or retailer-offer data was imported.

## Regression coverage

`backend.tests.test_khadlaj_official_spray_second_followup` verifies canonical IDs, provenance, variant uniqueness, attributes, GTIN handling, and family-registry alignment.
