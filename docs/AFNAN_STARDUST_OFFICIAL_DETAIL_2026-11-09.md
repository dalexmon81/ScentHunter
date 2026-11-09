# Afnan Stardust official detail reconciliation — 9 November 2026

## Existing canonical identity retained

The catalog already contained one Afnan identity:
- Product ID: `SH-AFNAN-STARDUST`
- Canonical name: `Stardust`
- Previous evidence: official Afnan collection listing

No duplicate canonical identity was created.

## Individual official detail evidence

Afnan's official Europe storefront product page identifies Stardust as:
- Extrait de Parfum
- 100 ml
- Unisex

Official product page: https://www.afnaneurope.com/products/stardust

The catalog identity was upgraded in place to `source_verified_name`. Its source URL, product URL and evidence URL now point to the individual official product page. One explicit 100 ml Extrait de Parfum variant was added with variant-level evidence.

## Family registry and regression coverage

- Existing `afnan_catalog` family entry retained.
- Stardust family format synchronized to 100 ml.
- Regression test checks the preserved canonical product ID, source provenance, concentration, variant ID, size, variant evidence URL and family-registry format.

## Integrity and scope

- No new canonical product identity.
- No prices, retailer offers, stock, shipping, GTINs, MPNs or affiliate data added.
- No other brand records changed.
- This PR is stacked on the Afnan 9-series/Supremacy/Turathi evidence branch.
