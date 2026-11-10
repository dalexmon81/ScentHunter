# Khadlaj official product-page reconciliations — 10 November 2026

## Result

Three existing Khadlaj canonical identities were reconciled to individual brand-owned product pages. No new canonical identities were created.

| Existing identity | Size | Concentration | GTIN |
|---|---:|---|---|
| Cream Velvet | 100 ml | Extrait de Parfum | 6291107978819 |
| Island | 100 ml | Extrait de Parfum | 6291107978789 |
| Island Sun | 100 ml | Extrait de Parfum | 6298043073080 |

## First-party evidence

- Cream Velvet: https://khadlaj-perfumes.com/products/cream-velvet-100-ml-extrait-de-parfum-for-women-best-perfumes
- Island: https://khadlaj-perfumes.com/collections/all/products/island-100-ml-extrait-de-parfum-spray-for-men-and-women
- Island Sun: https://khadlaj-perfumes.com/products/khadlaj-island-sun-100-ml-extrait-de-parfum

Each individual official page states the fragrance name, 100 ml size, Extrait de Parfum concentration, and product SKU/GTIN. The official collection pages were used only as additional discovery context.

## Catalog changes

- Reuse the existing canonical product IDs for all three fragrances.
- Upgrade each identity to `source_verified_name` and set its individual official product URL as `source_url`, `source_product_url`, and `source_evidence_url`.
- Cream Velvet had no explicit variant; add exactly one 100 ml Extrait de Parfum variant.
- Island and Island Sun already had one matching 100 ml Extrait variant each; retain those variants and upgrade their evidence URLs and GTINs instead of duplicating them.
- Keep the existing `khadlaj_catalog` family-registry identities and 100 ml format declarations.

No price, stock, availability, shipping, or retailer-offer data is copied into the canonical catalog.

## Regression coverage

`backend.tests.test_khadlaj_cream_velvet_official_variant` checks all three identity records, individual official-page provenance, exactly one matching variant per product, GTINs, concentration, size, and family-registry alignment.
