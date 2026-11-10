# Khadlaj official product-page reconciliations — 10 November 2026 (batch 2)

## Result

Seven existing Khadlaj canonical identities were reconciled to individual brand-owned product pages. No new canonical product identities were created.

| Existing identity | Size | Concentration | GTIN |
|---|---:|---|---|
| Nuha Bon Bon | 85 ml | Eau de Parfum | 6298043070317 |
| Nuha Cherry Blush | 85 ml | Eau de Parfum | 6291107979175 |
| Strawberry Shake | 100 ml | Eau de Parfum | 6298043070652 |
| Nafais Magrib | 100 ml | Eau de Parfum | 6298043070010 |
| Mansion | 100 ml | Eau de Parfum | 6298043070331 |
| Peach Velvet | 100 ml | Extrait de Parfum | 6298043070034 |
| Onyx Gold | 100 ml | Eau de Parfum | 6298043070140 |

## First-party evidence

- Nuha Bon Bon: https://khadlaj-perfumes.com/products/nuha-bon-bon-strawberry-vanilla-ice-cream-gourmand-perfume-for-women-online
- Nuha Cherry Blush: https://khadlaj-perfumes.com/products/nuha-cherry-blush-85-ml-edp-spray-for-women-online-shopping-uae
- Strawberry Shake: https://khadlaj-perfumes.com/products/strawberry-shake-eau-de-parfum-spray-for-women-dubai-uae-online
- Nafais Magrib: https://khadlaj-perfumes.com/collections/unisex-1/products/khadlaj-nafais-magrib-100-ml-eau-de-parfum-for-men-women
- Mansion: https://khadlaj-perfumes.com/collections/unisex-1/products/mansion-eau-de-parfum-spray-for-unisex-scents-by-khadlaj-dubai-uae
- Peach Velvet: https://khadlaj-perfumes.com/collections/best-selling-perfumes/products/peach-velvet-100-ml-extrait-de-parfum-for-women-top-women-fragrance-brand-uae
- Onyx Gold: https://khadlaj-perfumes.com/ar/collections/for-him/products/khadlaj-onyx-gold-100-ml-eau-de-parfum-for-men-luxury-perfume-online-dubai-uae

The individual official pages provide product name, size, concentration and SKU/GTIN. Collection pages were used only for discovery. No price, stock, availability, shipping or retailer-offer data is copied into the canonical catalog.

## Catalog changes

- Reused all seven existing canonical product IDs.
- Upgraded each identity to `source_verified_name` and stored the official product URL in `source_url`, `source_product_url` and `source_evidence_url`.
- Added exactly one explicit size/concentration variant for each product, with the official GTIN and page evidence.
- Aligned every matching Khadlaj family-registry row with the verified size.
- Added no duplicate canonical product identities.

## Regression coverage

`backend.tests.test_khadlaj_seven_official_variants` checks identity uniqueness, provenance, exactly one variant per product, GTIN, concentration, size and all matching family-registry rows.
