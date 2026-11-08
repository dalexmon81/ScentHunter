# Khadlaj main-range official product reconciliation — 8 November 2026

## Scope

This change promotes 16 missing fragrance identities already present in the `khadlaj_catalog` family registry, using individual product pages on the brand-owned Khadlaj Perfumes Official E-Store.

## Added canonical products and variants

| Canonical identity | Size | Type / concentration |
|---|---:|---|
| Bleu Glace | 100 ml | Extrait de Parfum |
| Code Marron Oud | 100 ml | Eau de Parfum |
| Code Rouge Amour | 100 ml | Eau de Parfum |
| Code Verde Sublime | 100 ml | Eau de Parfum |
| Code Viola Nectar | 100 ml | Eau de Parfum |
| Gaith | 100 ml | Eau de Parfum |
| Hareem Al Sultan Blue | 35 ml | Concentrated perfume oil |
| Maya | 20 ml | Concentrated perfume oil |
| Mocha Latte | 100 ml | Extrait de Parfum |
| Rose And Romance | 100 ml | Eau de Parfum |
| Shiyaaka Men | 100 ml | Eau de Parfum |
| Uno Durable | 100 ml | Eau de Parfum |
| Uno Intimo | 100 ml | Eau de Parfum |
| Uno Lusso | 100 ml | Eau de Parfum |
| Uno Sensuale | 100 ml | Eau de Parfum |
| Wow Oud | 100 ml | Eau de Parfum |

Each product record stores its individual official product page in `source_url`, `source_evidence_url`, and `source_product_url`. Each has one corresponding variant with the same official URL.

The two concentrated perfume oils, Maya (20 ml) and Hareem Al Sultan Blue (35 ml), deliberately have no EDP/Extrait concentration value. They remain distinct oil formats, not spray variants. Bleu Glace and Mocha Latte are Extrait de Parfum; the other 12 added records are Eau de Parfum.

## Spelling reconciliation

The family registry had a separate `Sensuos Night` entry, while the catalog already contained the official product name `Sensuous Night`. The brand-owned product page title uses `SENSUOS NIGHT`, while the description uses `Sensuous Night`. This PR:
- keeps the existing canonical product ID;
- adds `Sensuos Night` and `Khadlaj Sensuos Night` as aliases;
- merges the duplicate family-registry rows into one `Sensuous Night` row;
- adds the individual product page as `source_evidence_url` and on the variant;
- preserves the original collection `source_url` and `source_listed_name` status from the spray-harvest PR.

No second Sensuos/Sensuous Night product is created.

## Catalog changes

- Adds 16 canonical products and 16 matching variants.
- Updates the existing Khadlaj family-registry format sizes.
- Adds aliases for public spelling variants: `Code Viola Necter`, `Shiyaaka For Men`, and `La Fede Uno ...` names where used by the official product pages.
- Does not copy price, offer, stock, or availability data.

## Snapshot after change

- Total canonical products: 2,123
- Total variants: 381
- Khadlaj canonical products: 165
- Khadlaj variants: 85
- Duplicate product IDs: 0
- Duplicate variant IDs: 0
- Orphan variants: 0
- Parent format mismatches: 0

## Regression protection

`backend/tests/test_khadlaj_main_range_official_reconciliation.py` checks all 16 official pages, their sizes and concentrations, oil handling, family-registry alignment, the Sensuos/Sensuous alias merge, and ID integrity.
