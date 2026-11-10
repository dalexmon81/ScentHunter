# Afnan official evidence — third batch — 10 November 2026

Continues cumulatively from PR #723. All four canonical products already existed; this batch adds five official EDP size variants without creating duplicate product identities.

## Confirmed variants

| Existing canonical product | Concentration | Size | Individual official Afnan source |
|---|---|---:|---|
| 9 PM Pour Femme | Eau de Parfum | 100 ml | https://afnan.com/products/9-pm-pour-femme |
| Supremacy Silver | Eau de Parfum | 100 ml | https://afnan.com/products/supremacy-silver |
| Supremacy Silver | Eau de Parfum | 150 ml | https://afnan.com/products/supremacy-silver |
| Turathi Purple | Eau de Parfum | 90 ml | https://de.afnan.com/products/turathi-purple-femme |
| TURATHI RED | Eau de Parfum | 90 ml | https://saudi.afnan.com/products/turathi-red-femme |

The official product pages explicitly expose the stated concentration and volume. Supremacy Silver exposes both 100 ml and 150 ml options on its official page. Turathi Purple and Turathi Red use Afnan's official regional storefronts, not third-party retailer pages.

## Data safeguards

- Reuse the four existing canonical product IDs.
- Synchronize product-level `formats_ml` and the Afnan family-registry entries.
- Create one variant per confirmed size, with individual source evidence.
- No GTIN is added; none was independently verified in the reviewed page details.
- No price, stock, availability, shipping or retailer-offer data is imported.
- Regression coverage checks source provenance, variant identity, registry parity, uniqueness, orphan prevention and offer-data separation.

## Snapshot

Base at PR #723: 2,225 canonical products / 1,248 variants / 34 family-registry families.

Expected after this batch: 2,225 canonical products / 1,253 variants / 34 families.
