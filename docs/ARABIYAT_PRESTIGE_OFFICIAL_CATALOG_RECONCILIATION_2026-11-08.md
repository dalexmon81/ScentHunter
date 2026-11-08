# Arabiyat Prestige official Al Youm and Red Oud reconciliation — 8 November 2026

## Scope

Five canonical identities already listed in the `arabiyat_prestige_catalog` family registry were absent from the catalog. Each now has an individual product page on the brand-owned Arabiyat Prestige store.

## Added products and variants

| Product | Size | Concentration |
|---|---:|---|
| Attar Al Youm Black | 100 ml | Eau de Parfum |
| Musk Al Youm | 100 ml | Eau de Parfum |
| Oud Al Youm | 100 ml | Eau de Parfum |
| Red Oud | 100 ml | Eau de Parfum |
| Al Shujae | 100 ml | Eau de Parfum |

Official product pages:
- Attar Al Youm Black: https://arabiyatprestige.com/products/attar-al-youm-edp-100ml-1
- Musk Al Youm: https://arabiyatprestige.com/collections/arabiyat-prestige/products/musk-al-youm-edp-100ml-1
- Oud Al Youm: https://arabiyatprestige.com/products/oud-al-youm-edp-100ml-1
- Red Oud: https://arabiyatprestige.com/products/red-oud-edp-100ml-1
- Al Shujae: https://arabiyatprestige.com/products/al-shujae-edp-100-ml

Each record is marked `source_verified_name`, stores its individual official page in `source_url`, `source_evidence_url`, and `source_product_url`, and has one matching 100 ml Eau de Parfum variant.

## Guardrails

- No new canonical identities beyond the five already listed in the registry.
- No prices, offers, stock, or availability copied into the catalog.
- No size or concentration inferred from third-party retailers; the values above are stated on the official brand pages.

## Snapshot after change

- Arabiyat Prestige canonical products: 123
- Arabiyat Prestige variants: 27
- New canonical products: 5
- New variants: 5

## Regression protection

`backend/tests/test_arabiyat_prestige_official_catalog_reconciliation.py` checks all five individual official pages, their 100 ml EDP variants, family-registry format alignment, and unique product/variant IDs.
