# Recovered official catalog records — 10 November 2026

## Scope

A branch comparison across PRs #636–#641 and the newer cumulative PR #703 showed several historical records that appeared to be missing. This audit distinguishes true omissions from superseded IDs and incorrect brand attribution.

## Restored: Arabiyat Prestige Marwa

The current official Arabiyat Prestige product page identifies Marwa as an unisex Eau de Parfum, 100 ml:
https://arabiyatprestige.com/products/arabiyat-prestige-marwa-edp-100ml-unisex

- Reuse product ID SH-ARABIYAT-PRESTIGE-7bf3b46e.
- Reuse the previously established variant ID SHV-SH-ARABIYAT-PRESTIGE-7bf3b46e-100-EDP.
- Set identity status to source_verified_name.
- Add 100 ml, Eau de Parfum and Unisex.
- Add the matching 100 ml format to arabiyat_prestige_catalog.
- No GTIN is added because the official page does not expose one.

## Kismet: old variant ID was superseded

The current Maison Alhambra USA product page explicitly identifies Kismet for Men as 3.4 oz / 100 ml Eau de Parfum and exposes barcode 6291107459257:
https://maisonalhambra-usa.com/products/maison-alhambra-kismet-eau-de-parfum-for-men

PR #636/#641 used the older variant ID ending in `100-000`. PR #703 already contains the verified 100 ml Kismet for Men variant ending in `100-MEN`, with the same canonical product ID and barcode. The older ID must not be reintroduced as a duplicate.

## Gulf Orchid / Maison Asrar attribution reconciliation

PR #636 included Vanilla Aura and Vanilla Voyage under Gulf Orchid product IDs. The current official Gulf Orchid storefront labels both products as Maison Asrar, and PR #703 already contains them under the existing Maison Asrar IDs:
- SH-MAISON-ASRAR-bab16c06 — Vanilla Aura
- SH-MAISON-ASRAR-19d98178 — Vanilla Voyage

The duplicate Gulf Orchid IDs are intentionally not restored. The official product pages support the Maison Asrar attribution:
- https://shop-gulforchid.com/products/vanilla-aura
- https://shop-gulforchid.com/products/maison-asrar-vanilla-voyage-eau-de-parfum

## Khadlaj collection-only record not restored

Musk Pure Musk Blend Creation of Iqbal appears in the older PR #636 branch only with a generic collection-page source. No individual official product detail page establishing the product's size and concentration was recovered in this audit. It remains excluded rather than being reintroduced with guessed variant data.

## Regression coverage

`backend.tests.test_recovered_official_catalog_records_2026_11_10` checks the restored Marwa variant, the superseded Kismet variant ID, the Maison Asrar attribution of Vanilla Aura and Vanilla Voyage, and global catalog integrity.
