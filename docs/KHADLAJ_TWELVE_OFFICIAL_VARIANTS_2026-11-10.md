# Khadlaj official product-page reconciliation — 10 November 2026

## Result

Twelve existing Khadlaj canonical identities were reconciled against individual official product pages. Ten variants were added; two existing variants (Empire Crown and Empire Regent) were retained and enriched with the canonical product-page URL. No new canonical product identities were created.

| Product | Size | Concentration | GTIN / official SKU |
|---|---:|---|---|
| Biscotti Caramel Pop | 100 ml | Extrait de Parfum | 6291107979953 |
| Stellar Musk | 100 ml | Eau de Parfum | official SKU KM-689/2 or KM-689 (not a GTIN) |
| Stellar Oud | 100 ml | Eau de Parfum | official SKU KM-689/2 or KM-689 (not a GTIN) |
| Opus Reborn | 100 ml | Eau de Parfum | 6291107978130 |
| Karus Secret Musk | 100 ml | Eau de Parfum | 6291107975870 |
| Karus Blu Spice | 100 ml | Eau de Parfum | 6291107975856 |
| Karus Oud Fire | 100 ml | Eau de Parfum | 6291107975863 |
| Valor Mystique | 100 ml | Eau de Parfum | 6291107975993 |
| Valor Honor | 100 ml | Eau de Parfum | 6291107975962 |
| Valor Chivalry | 100 ml | Eau de Parfum | 6291107975986 |
| Empire Crown | 100 ml | Eau de Parfum | 6291107975887 |
| Empire Regent | 100 ml | Eau de Parfum | 6291107975900 |

## First-party evidence

- Biscotti Caramel Pop: https://khadlaj-perfumes.com/products/biscotti-caramel-pop-100-ml-extrait-de-parfum-spray-for-men-women-gourmand-lovers-fragrance-dubai-uae
- Stellar Musk: https://khadlaj-perfumes.com/collections/women-perfume/products/stellar-musk-100-ml-edp-spray-for-women
- Stellar Oud: https://khadlaj-perfumes.com/products/stellar-oud-100-ml-edp-spray-for-men-women
- Opus Reborn: https://khadlaj-perfumes.com/products/opus-reborn-100-ml-edp-spray-for-men-fragrance-to-shop-online-dubai-uae
- Karus Secret Musk: https://khadlaj-perfumes.com/products/karus-secret-musk-100-ml-edp-spray
- Karus Blu Spice: https://khadlaj-perfumes.com/products/karus-blu-spice-100-ml-edp-spray
- Karus Oud Fire: https://khadlaj-perfumes.com/products/karus-oud-fire-100-ml-edp-spray
- Valor Mystique: https://khadlaj-perfumes.com/products/valor-mystique-100-ml-edp-spray
- Valor Honor: https://khadlaj-perfumes.com/collections/mens-perfumes/products/valor-honor-100-ml-edp-spray
- Valor Chivalry: https://khadlaj-perfumes.com/collections/mens-perfumes/products/valor-chivalry-100-ml-edp-spray
- Empire Crown: https://khadlaj-perfumes.com/products/empire-crown-100-ml-edp-spray-best-perfume-spray-for-men-online-dubai-uae
- Empire Regent: https://khadlaj-perfumes.com/products/empire-regent-100-ml-edp-spray-luxury-perfume-for-men-and-women-dubai-uae

For Stellar Musk and Stellar Oud, the official pages identify their internal SKUs as KM-689/2 and KM-689 respectively; these alphanumeric SKUs are deliberately not written into the GTIN field. The remaining numeric identifiers are the official page SKUs/GTINs.

## Catalog changes

- Reused the twelve existing canonical product IDs.
- Upgraded product identity status and stored individual official product-page provenance.
- Added one explicit variant for each product that did not already have one.
- Preserved the existing Empire Crown and Empire Regent variant IDs and evidence unchanged.
- Added GTINs only where the official page provides a numeric identifier; no GTIN was invented for Stellar Musk or Stellar Oud.
- Updated the correct family-registry row for each product, using its existing family ID.
- No product identities were duplicated and no existing variants were overwritten.

No price, stock, availability, shipping, or retailer-offer data was imported.

## Regression coverage

`backend.tests.test_khadlaj_official_spray_followup` verifies canonical IDs, provenance, variant uniqueness, attributes, GTIN handling, and family-registry alignment.
