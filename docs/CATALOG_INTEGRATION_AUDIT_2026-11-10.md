# Catalog integration audit — 10 November 2026

## Integration scope

This branch starts from PR #641's exact head commit (`0a6f478269a61170c68f738751e318c2565ef557`) and integrates the six distinct verified variants from PR #638 for three existing Velixir canonical products:

- Comus — 35 ml and 100 ml Extrait de Parfum
- Ether — 35 ml and 100 ml Extrait de Parfum
- Panacea — 35 ml and 100 ml Extrait de Parfum

Existing product IDs were preserved. The individual first-party product pages on `velixirparfums.store` are retained as evidence. The family registry now declares both verified sizes.

## Baseline and resulting integrity snapshot

The PR #641 base contained 2,206 products and 872 variants. The integration adds six variants, resulting in 2,206 products and 878 variants.

Local structural checks performed against the exact generated JSON before commit:
- duplicate product IDs: 0
- duplicate variant IDs: 0
- orphan variants: 0
- duplicate (product_id, size_ml) pairs: 0

The repository's existing catalog integrity tests remain applicable. An additional global integration test protects product IDs, variant IDs, parent references, product-size uniqueness, and prevents offer fields from entering canonical variants.

## Upstream PR status

At audit time PRs #636–#641 were all open draft PRs, none merged. Their branch dependencies are not a single cumulative linear chain:
- #637 is based on #636
- #641 is based on #640
- #638 and #639 are separate branches from `catalog/requested-brand-harvest-2026-11-08`
- #640 is also based on that requested-brand harvest branch

This integration does not merge any PR. It explicitly includes the verified data from #638 on the PR #641 head.

## Intentionally not integrated in this pass

- PR #639 (Arabiyat Prestige): source-verified Marwa 100 ml EDP update is a separate, non-overlapping delta. It should be integrated in a follow-up after comparing the brand registry and workflow changes carefully.
- PRs #636–#637 (Gulf Orchid and Maison Asrar): add four Gulf Orchid products and audit the Maison Asrar New Arrivals page. These changes are not present in #641 and require explicit integration from their chain.
- PR #640 (Maison Asrar detail provenance upgrades): three existing identities gain official detail-page provenance; no variants are inferred. This is a separate follow-up.
- PR #641 Khadlaj updates are retained as-is.

No prices, stock, retailer availability, shipping, or offers are inserted into the canonical catalog.
