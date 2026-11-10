# Cumulative official brand variant integration — 10 November 2026

## Rebased integration

This draft is based on the latest head of the Khadlaj consolidation branch at rebase time. It integrates independent source-backed changes from PRs #636–#640 without merging or closing those source PRs.

## Integrated work

- **Gulf Orchid:** Maze, Mosaic, Rice Milk and Royal Rose, with individual official product-page evidence and explicit 100 ml Eau de Parfum variants. PR #637 carries the changes from #636, so they are integrated once.
- **Maison Asrar:** official new-arrival identities are reconciled against individual product pages, reusing existing canonical identities.
- **Velixir:** Comus, Ether, Orpheus and Panacea receive official 35 ml and 100 ml Extrait de Parfum variants. Sample vials and the four-bottle bundle remain excluded.
- **Arabiyat Prestige:** official new-launch page evidence and explicitly documented variants are integrated.
- **Maison Asrar detail audit:** Dubai London, Dubai Miami and Hikaya retain existing IDs and individual official-page provenance. No unsupported sizes or concentrations are inferred.

## Merge safeguards

- Existing canonical product IDs are preserved.
- Latest Khadlaj product and test changes from the moving base branch are retained.
- Three-way reconciliation found no product, variant or family-registry field conflicts.
- The later Khadlaj Sueño/Sueno cleanup is retained.
- No prices, stock, availability, shipping or retailer offers are imported.

## Structural validation

- 2,210 canonical products.
- 969 explicit variants.
- Zero duplicate product IDs, variant IDs, normalized brand/name identities, product/size/concentration tuples or GTINs.
- Zero orphan variants.
- Zero duplicate Khadlaj family-registry canonical names.

GitHub Actions is the final validation gate for this draft.
