# Cumulative official brand variant integration — 10 November 2026

## Integration base

This draft is based on the current Khadlaj cumulative catalog candidate from PR #649. It preserves that branch's canonical identities and variants, then integrates the independent official-source changes from PRs #636–#640.

## Integrated source work

- **Gulf Orchid:** four canonical identities (Maze, Mosaic, Rice Milk and Royal Rose) with individual official product-page evidence and explicit 100 ml Eau de Parfum variants. The #637 branch carries the changes from #636, so they are integrated once.
- **Maison Asrar:** the twelve official new-arrival identities are reconciled against individual official product pages; existing canonical identities are reused.
- **Velixir:** Comus, Ether, Orpheus and Panacea receive the official 35 ml and 100 ml Extrait de Parfum variants. Sample vials and the four-bottle bundle remain excluded.
- **Arabiyat Prestige:** official new-launch product-page evidence and explicitly listed variants are integrated. No sizes or concentrations are inferred beyond source-backed entries.
- **Maison Asrar detail audit:** Dubai London, Dubai Miami and Hikaya retain their existing IDs and individual page provenance; no unsupported variants are inferred.

## Merge decisions

- Existing canonical product IDs are preserved.
- PR #637 carries the four Gulf Orchid additions from PR #636; those records are integrated once.
- The later Khadlaj consolidation's intentional Sueño/Sueno family-registry cleanup is retained; older parallel registry snapshots do not reintroduce the removed row.
- The product and variant changes from the selected source branches had no conflicting field edits against the common base.
- No prices, stock, availability, shipping or retailer offers are added.

## Structural validation before CI

- 2,210 canonical products.
- 969 explicit variants.
- Zero duplicate product IDs.
- Zero duplicate variant IDs.
- Zero duplicate normalized brand/name identities.
- Zero duplicate product/size/concentration tuples.
- Zero orphan variants.
- Zero duplicate GTINs.

Catalog CI includes the source-specific regression modules and cumulative Khadlaj integrity checks. These structural counts are not a substitute for the final GitHub Actions result.
