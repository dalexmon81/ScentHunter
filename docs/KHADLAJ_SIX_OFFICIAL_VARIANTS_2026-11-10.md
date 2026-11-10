# Khadlaj official variant reconciliation – 2026-11-10

## Scope

This change completes nine existing Khadlaj canonical identities using official Khadlaj product detail pages. It does not create new product identities and does not import retailer offers, prices, stock, or shipping data.

| Product | Canonical ID | Size | Concentration | GTIN |
|---|---|---:|---|---|
| Muse | SH-KHADLAJ-MUSE | 100 ml | Eau de Parfum | 6298043072748 |
| Sueno | SH-KHADLAJ-SUENO | 100 ml | Extrait de Parfum | 6298043072809 |
| Saraya | SH-KHADLAJ-SARAYA | 60 ml | Extrait de Parfum | 6298043072380 |
| Qarar | SH-KHADLAJ-QARAR | 60 ml | Extrait de Parfum | 6298043071628 |
| Ihthiraam | SH-KHADLAJ-IHTHIRAAM | 60 ml | Extrait de Parfum | 6298043072229 |
| Icon | SH-KHADLAJ-ICON | 100 ml | Eau de Parfum | 6298043071215 |
| Zayaan Silver | SH-KHADLAJ-ZAYAAN-SILVER | 100 ml | Eau de Parfum | 6298043070058 |
| Onyx Gold | SH-KHADLAJ-6494ea68 | 100 ml | Eau de Parfum | 6298043070140 |
| Peach Velvet | SH-KHADLAJ-PEACH-VELVET | 100 ml | Extrait de Parfum | 6298043070034 |

## Official evidence

- Muse: https://khadlaj-perfumes.com/collections/deals/products/khadlaj-muse-100-ml-eau-de-parfum-spray-for-women
- Sueno: https://khadlaj-perfumes.com/collections/best-selling-perfumes/products/sueno-100ml-extrait-de-parfum-for-women
- Saraya: https://khadlaj-perfumes.com/collections/flash-sale/products/khadlaj-saraya-60-ml-extrait-de-parfum-spray-for-men-women
- Qarar: https://khadlaj-perfumes.com/collections/best-selling-perfumes/products/khadlaj-qarar-unisex-bold-oriental-extrait-de-parfum
- Ihthiraam: https://khadlaj-perfumes.com/products/ihthraam-extrait-de-parfum-spray-oriental-unisex-fragrance
- Icon: https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-icon-100-ml-eau-de-parfum-spray-for-men
- Zayaan Silver: https://khadlaj-perfumes.com/products/zayaan-silver-fresh-aquatic-spicy-woody-eau-de-parfum-for-men
- Onyx Gold: https://khadlaj-perfumes.com/products/khadlaj-onyx-gold-100-ml-eau-de-parfum-for-men-luxury-perfume-online-dubai-uae
- Peach Velvet: https://khadlaj-perfumes.com/collections/all/products/peach-velvet-100-ml-extrait-de-parfum-for-women-top-women-fragrance-brand-uae

## Data integrity

- Reused all nine existing canonical product IDs.
- Added one explicit variant per product, with size, concentration, GTIN and official evidence URL.
- Updated the Khadlaj family registry formats.
- Consolidated the duplicate Sueño / Sueno family-registry row into the catalog's existing canonical spelling Sueno, retaining Sueño as an alias.
- No price, stock, availability, shipping or retailer offer fields were added.

## Regression coverage

The new test verifies canonical identity uniqueness, source provenance, variant count and IDs, size, concentration, GTIN, and family-registry consistency.
