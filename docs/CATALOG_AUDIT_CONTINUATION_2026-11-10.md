# Catalog audit continuation — 10 November 2026

## Starting point

This branch continues from the cumulative catalog head in PR #705:
- Branch: `catalog/afnan-official-variants-2026-11-10`
- Commit: `f19cf080fe6feb785e95241176776de78027e659`
- Parent PR #705 remains open and draft; no merge to `main`.

The exact PR #705 head has successful catalog validation runs:
- Run #2868: https://github.com/dalexmon81/ScentHunter/actions/runs/42806766565
- Run #2867: https://github.com/dalexmon81/ScentHunter/actions/runs/42806533844

The cumulative source snapshot was independently inspected:
- 2,213 canonical product identities
- 1,160 variants
- 34 family-registry families
- 1,239 source-verified names and 974 source-listed names
- 241 verified products currently without variants

Integrity results on this exact branch:
- 0 duplicate product IDs
- 0 duplicate variant IDs
- 0 duplicate normalized brand/name pairs
- 0 duplicate product/size/concentration tuples
- 0 duplicate non-empty GTINs
- 0 duplicate family IDs
- 0 orphan variants
- 0 catalog products missing a family registry mapping
- 0 variants outside their parent declared sizes
- 0 variant rows containing commercial offer fields

## Important remaining baseline risk

The existing requested-brand test contains lower bounds for twenty brands. Several values were written against an older snapshot and are greater than the actual counts in the verified #705 catalog. Before using that test as a reliable completion gate, reconcile each lower bound with the latest official-source evidence and the actual branch content. Do not raise or lower thresholds simply to make CI green; preserve the evidence trail for every change.

Current verified product counts on #705:
- Maison Asrar: 120
- Paris Corner: 254
- Al Wataniah: 86
- Armaf: 218
- Khadlaj: 115
- Afnan: 87
- Maison Alhambra: 232
- Velixir: 28
- Arabiyat Prestige: 118
- Gulf Orchid: 34
- Lattafa: 135
- Zimaya: 76
- Al Haramain: 149
- Assaf: 140

## Audit rules

1. Continue from this branch only; do not rebuild the catalog from `main`.
2. Preserve canonical product IDs and existing variant IDs.
3. Verify missing or incomplete products from official brand product pages or another clearly identified primary source.
4. Add size, concentration, gender and GTIN only when explicitly supported by evidence.
5. Keep disagreements unresolved rather than guessing. In particular, preserve the documented unresolved concentration for Sawaar Vanille Blanc.
6. Keep products, variants and family registry synchronized.
7. Never import price, stock, availability, shipping or retailer offer information into the canonical identity catalog.
8. Add regression tests for each verified batch and retain global collision, orphan and family-mapping checks.

## First follow-up targets

Prioritize brands with large listing-to-catalog gaps, especially Maison Alhambra, Paris Corner, Khadlaj, Armaf and Maison Asrar. A listing count alone is not proof of a missing canonical perfume: filter out bundles, samples, body care, home fragrances and duplicated size presentations; resolve sub-brand attribution before adding anything.
