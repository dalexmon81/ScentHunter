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

## Existing brand coverage control (do not weaken)

The repository's pre-existing `backend/tests/test_requested_brand_catalog_coverage.py` already protects these 20 reconciled minimums. Keep the original baseline and investigate any failures against the exact source branch rather than editing thresholds to make CI pass:

- Velixir 28; Maison Asrar 120; Swiss Arabian 41; Paris Corner 254; Khadlaj 115.
- Bujairami 142; Assaf 140; Al Wataniah 86; French Avenue 119; Arabiyat Prestige 118.
- Gulf Orchid 32; Afnan 87; Lattafa 135; Aromatix 12; Zimaya 76.
- Al Haramain 149; Games of Spades 32; Maison Alhambra 226; Mykonos 72; Armaf 218.

At the verified PR #705 head, the observed counts meet or exceed those minimums. The exact current counts for the less recently targeted brands should be preserved in follow-up snapshots.

## First follow-up targets

Prioritize brands with unresolved official-listing reconciliation rather than simply choosing the largest numeric gap. Maison Alhambra, Paris Corner, Khadlaj, Armaf and Maison Asrar remain useful candidates, but the latest work already includes large portions of those families. For every new batch:

1. Identify the exact official brand storefront and the relevant perfume-only paginated collection.
2. Capture each page's product title and individual product URL; filter bundles, samples, body care, home fragrance, air fresheners and unrelated sub-brands.
3. Compare normalized brand/name identity to the current catalog before adding any canonical record.
4. Fetch individual product pages for size/concentration/GTIN evidence. A collection listing proves a listed name only, not a bottle variant.
5. Reuse canonical IDs for existing products. If product ownership, identity, GTIN or format is ambiguous, document and quarantine the candidate rather than inventing a record.
6. Add focused tests for each batch and update `family_registry.json` only with source-backed formats and product identities.
7. Run the whole catalog seed validation and global integrity suite on the exact PR head.
