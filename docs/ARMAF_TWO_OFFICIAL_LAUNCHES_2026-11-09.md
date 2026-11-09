# Armaf — two official EU product-page launches — 9 November 2026

## Scope

Adds two new Armaf canonical identities from individual product pages on official Armaf European storefronts.

## Added products

| Product | Official page | Size | Concentration |
|---|---|---:|---|
| Dunescape Dubai | https://armaf.eu/products/dunescape | 100 ml | Extrait de Parfum |
| Check Mate White Knight | https://cz.armaf.eu/en/products/check-mate-white-knight | 100 ml | Eau de Parfum |

## Changes

- Adds two canonical products and their explicit 100 ml variants.
- Registers both in `armaf_catalog`.
- Uses individual official product-page URLs for source, product, and evidence fields.
- Adds focused regression coverage and a CI step.
- No third-party retailer offers, prices, stock, or shipping data imported.

## Validation

The full catalog seed validation and dedicated two-product test must pass before review. Draft PR only; no changes to `main`.
