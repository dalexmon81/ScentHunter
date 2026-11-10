# Afnan official evidence — fourth batch — 10 November 2026

Continues cumulatively from PR #724. This batch upgrades three existing Afnan canonical identities from collection-listing provenance to individual official product-page provenance.

## Confirmed products and variants

| Existing canonical product | Concentration | Confirmed size(s) | Individual official Afnan source |
|---|---|---:|---|
| Supremacy Not Only Intense | Extrait de Parfum | 100 ml, 150 ml | https://it.afnan.com/products/supremacy-not-only-intense |
| Turathi Electric | Eau de Parfum | 90 ml | https://www.at.afnan.com/en/products/turathi-electric |
| Kiaana Crush | Eau de Parfum | 100 ml | https://us.afnan.com/products/kiaana-crush |

The Italian official storefront identifies Supremacy Not Only Intense as Extrait de Parfum and offers 100 ml and 150 ml variants. The Austrian official storefront identifies Turathi Electric as Eau de Parfum, 90 ml. The US official storefront identifies Kiaana Crush as Eau de Parfum, 100 ml.

## Data safeguards

- Reuse all three existing canonical product IDs.
- Preserve the two existing Supremacy Not Only Intense variant IDs; add official page evidence to those records.
- Add only the two missing variants for Turathi Electric and Kiaana Crush.
- Synchronize product-level concentration/formats and Afnan family-registry formats.
- No GTIN is added because none was independently verified in the reviewed page details.
- No price, stock, availability, shipping or retailer-offer data is imported.
- Add focused regression coverage for provenance, variant identity, registry parity, uniqueness, orphan prevention and offer-data separation.
- Register both the previous third-batch test and this fourth-batch test in catalog seed CI.

## Snapshot

Base at PR #724: 2,225 canonical products / 1,253 variants / 34 registry families.

Expected after this batch: 2,225 canonical products / 1,255 variants / 34 registry families.
