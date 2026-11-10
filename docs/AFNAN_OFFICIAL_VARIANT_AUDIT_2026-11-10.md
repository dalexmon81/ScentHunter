# Afnan official variant audit — 10 November 2026

## Scope

This follow-up reconciles four existing Afnan canonical identities against individual product pages on Afnan's official regional storefronts. Existing product IDs are reused; no duplicate canonical products are added.

## Official product-page evidence

| Product | Official product page | Type | Volume | Audience |
|---|---|---|---:|---|
| 9 AM Dive | https://www.de.afnan.com/en/products/9-am-dive | Eau de Parfum | 100 ml | Unisex |
| Rare Reef | https://www.at.afnan.com/en/products/rare-reef | Extrait de Parfum | 100 ml | Unisex |
| Turathi Brown Homme | https://www.at.afnan.com/en/products/turathi-brown-homme | Eau de Parfum | 90 ml | Pour Homme |
| Historic Olmeda | https://www.at.afnan.com/products/historic-olmeda | Eau de Parfum | 100 ml | Pour Homme |

The official pages explicitly expose type and volume in the product detail section. No GTIN/EAN/barcode was exposed in the retrieved official page content, so no GTIN is added.

## Catalog changes

- Reuse canonical IDs SH-AFNAN-9e3c80fa, SH-AFNAN-e408d61b, SH-AFNAN-5cdc0bae and SH-AFNAN-62b409e4.
- Upgrade the four existing source-listed identities to source-verified names.
- Add one product variant per verified official size and concentration.
- Add the matching format to the existing Afnan family-registry entry.
- Preserve all existing product and variant IDs outside this batch.
- Do not import price, stock, availability, shipping or retailer-offer data.

## Regression coverage

`backend.tests.test_afnan_four_official_variants_2026_11_10` checks the four canonical IDs, product-page provenance, size, concentration, variant IDs, family-registry formats, unique IDs/GTINs/variant tuples, parent links and separation from commercial offer data.
