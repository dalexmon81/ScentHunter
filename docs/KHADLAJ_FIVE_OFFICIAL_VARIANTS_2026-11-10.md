# Khadlaj official product-page reconciliation — 10 November 2026

## Result

Five existing Khadlaj canonical identities were reconciled to individual brand-owned product pages. No new canonical product identities were created.

| Existing identity | Size | Concentration | GTIN |
|---|---:|---|---|
| Muse | 100 ml | Eau de Parfum | 6298043072748 |
| Sueno | 100 ml | Extrait de Parfum | 6298043072809 |
| Saraya | 60 ml | Extrait de Parfum | 6298043072380 |
| Strawberry Shake | 100 ml | Eau de Parfum | 6298043070652 |
| Peach Velvet | 100 ml | Extrait de Parfum | 6298043070034 |

## First-party evidence

- Muse: https://khadlaj-perfumes.com/products/khadlaj-muse-100-ml-eau-de-parfum-spray-for-women
- Sueno: https://khadlaj-perfumes.com/collections/all/products/sueno-100ml-extrait-de-parfum-for-women
- Saraya: https://khadlaj-perfumes.com/products/khadlaj-saraya-60-ml-extrait-de-parfum-spray-for-men-women
- Strawberry Shake: https://khadlaj-perfumes.com/products/strawberry-shake-eau-de-parfum-spray-for-women-dubai-uae-online
- Peach Velvet: https://khadlaj-perfumes.com/products/peach-velvet-100-ml-extrait-de-parfum-for-women-top-women-fragrance-brand-uae

The individual official product pages provide the product-specific size, concentration, and SKU/GTIN recorded above. Collection pages were not used as evidence for variant attributes.

## Catalog changes

- Reused the five existing canonical product IDs.
- Upgraded their identity status to `source_verified_name` and recorded the individual official product page in `source_url`, `source_product_url`, and `source_evidence_url`.
- Added exactly one explicit size/concentration variant for each product, with the official GTIN and page evidence.
- Updated the existing `khadlaj_catalog` family registry rows with the verified size.
- No product identities were duplicated and no pre-existing variants were overwritten.

No price, stock, availability, shipping, or retailer-offer data is copied into the canonical catalog.

## Regression coverage

`backend.tests.test_khadlaj_official_variant_batch` verifies existing canonical IDs, official provenance, one variant per product, size, concentration, GTIN, and family-registry alignment.
