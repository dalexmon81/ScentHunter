# Afnan official product-page variant batch — 10 November 2026

This batch continues the cumulative catalog from PR #721 without regenerating canonical identities.

## Added verified variants

| Existing canonical product | Official concentration | Official size | Evidence |
|---|---:|---:|---|
| Cherry Bouquet | Eau de Parfum | 80 ml | https://afnan.com/products/cherry-bouquet |
| Historic Doria | Eau de Parfum | 100 ml | https://afnan.com/products/historic-doria |
| LA FLEUR BOUQUET | Eau de Parfum | 80 ml | https://afnan.com/products/la-fleur-bouquet |
| ORNAMENT POUR FEMME | Eau de Parfum | 100 ml | https://afnan.com/products/ornament-pour-femme |
| Ornament Purple | Eau de Parfum | 100 ml | https://afnan.com/products/ornament-purple |
| Portrait Abstract | Eau de Parfum | 100 ml | https://afnan.com/products/portrait-abstract |
| Supremacy in Heaven | Eau de Parfum | 100 ml | https://afnan.com/products/supremacy-in-heaven |
| Tribute Blue | Eau de Parfum | 100 ml | https://afnan.com/products/tribute-blue |

The individual Afnan product pages explicitly show the concentration and volume. Product names, canonical IDs and family-registry identities are reused from the existing catalog.

## Exclusions and data discipline

- No GTIN is added: the reviewed pages do not expose a verifiable GTIN in the product details available for this audit.
- No product identity is created or renamed.
- No size is inferred from a title, bottle image, ounce conversion, retailer listing or bundle.
- No price, stock, availability, shipping or retailer offer data is added.
- The eight matching family-registry entries are synchronized with the verified sizes.
- The new regression test checks canonical identity reuse, provenance, variant uniqueness, registry parity, orphan protection and offer-data separation.

## Snapshot before this batch

- 2,225 canonical products
- 1,233 variants
- 34 family-registry families

Expected after this batch: 2,225 canonical products and 1,241 variants.
