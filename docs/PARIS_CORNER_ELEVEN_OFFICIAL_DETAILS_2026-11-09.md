# Paris Corner — eleven official Europe product details — 9 November 2026

## Scope

This change upgrades eleven existing Paris Corner canonical identities. It creates no new canonical products and preserves every existing product ID.

## Individual official product evidence

| Product | Official detail page | Explicit size | Concentration |
|---|---|---:|---|
| Coconut Lagoon | https://de.pariscornereurope.com/en/products/coconut-lagoon | 100 ml | Eau de Parfum |
| Eshal Vanilla | https://de.pariscornereurope.com/en/products/paris-corner-eshal-vanilla-edp-u-100-ml | 100 ml | Eau de Parfum |
| Ibisco Nirvana | https://de.pariscornereurope.com/en/products/ibisco-nirvana | 65 ml | Eau de Parfum |
| Hurriya | https://de.pariscornereurope.com/en/products/paris-corner-hurriya-edp-u-100-ml | 100 ml | Eau de Parfum |
| Miel Vanille | https://de.pariscornereurope.com/en/products/pc-miel-vanille-edp-u-100-ml | 100 ml | Eau de Parfum |
| Qissa | https://de.pariscornereurope.com/en/products/qissa | 100 ml | Eau de Parfum |
| Fayora | https://de.pariscornereurope.com/en/products/pc-fayora-edp-w-100-ml | 100 ml | Eau de Parfum |
| Fayora Oshino | https://de.pariscornereurope.com/en/products/pc-fayora-oshino-edp-w-100-ml | 100 ml | Eau de Parfum |
| Qissa Gala | https://de.pariscornereurope.com/en/products/pc-qissa-gala-edp-w-100-ml | 100 ml | Eau de Parfum |
| Qissa Delicious | https://de.pariscornereurope.com/en/products/qissa-delicious | 100 ml | Eau de Parfum |
| Qissa Pink | https://de.pariscornereurope.com/en/products/qissa-pink | 100 ml | Eau de Parfum |

The Paris Corner Europe storefront identifies the concentration as EDP and shows the size on each product page. Ibisco Nirvana is 65 ml; the other ten are 100 ml.

## Catalog changes

- Upgraded all eleven existing records to `source_verified_name`.
- Set `source_url`, `source_product_url`, and `source_evidence_url` to the individual official product page.
- Added one explicit Eau de Parfum variant per identity, preserving the existing canonical product IDs.
- Synchronized `formats_ml` and concentration in the Paris Corner family registry.
- Added regression tests for evidence URLs, identity uniqueness, variant linkage, sizes, and concentration.
- Expanded the Paris Corner source-prefix regression guard to accept individual product pages on the official Paris Corner Europe storefront.
- No price, stock, shipping, or offer data was imported.

## Validation

Catalog seed validation and the dedicated eleven-product regression test must pass on this branch before review. No changes to `main`; draft PR only.
