# Catalog snapshot reconciliation — 8 November 2026

## Scope and source

This is a read-only reconciliation of `backend/product_catalog.json` and `backend/family_registry.json` at the head of the requested-brand catalog branch before this documentation-only follow-up:

- Source branch: `catalog/requested-brand-harvest-2026-11-08`
- Source commit: `50baaefcf8d2b1b5764cbaa40f691c8685ba5c56`
- Parent catalog baseline: PR #437, `catalog/consolidated-brand-catalog-2026-11-08`

No catalog rows, product identities, variants, retailer offers, prices, or availability values were changed for this reconciliation.

## Reconciled totals

| Measure | PR #437 baseline | PR #439 current head |
|---|---:|---:|
| Canonical product identities | 2,050 | 2,061 |
| Explicit variant rows | 212 | 291 |
| Family registry entries | 34 | 34 |
| Distinct brands in product seed | — | 22 |

The PR #439 head therefore adds **11 canonical identities** and **79 variant rows** relative to the PR #437 catalog baseline.

The correct current variant count is **291**, not 273. The 273 figure is the count before the 18 Mykonos 15 ml travel-size variants were included: 273 + 18 = 291.

## Twenty requested brands

The twenty brands in `backend/tests/test_requested_brand_catalog_coverage.py` account for 2,058 identities:

- **186** rows marked `source_verified_name`
- **1,872** rows marked `source_listed_name`

These are repository evidence labels. `source_verified_name` means the record has individual product-page evidence in the catalog workflow; it is not a blanket assertion that every source domain is brand-owned. `source_listed_name` indicates listing-level evidence and should not be described as individual product-page verification.

| Brand | Identities | Individual-page verified | Listing-level | Variants |
|---|---:|---:|---:|---:|
| Velixir | 28 | 28 | 0 | 0 |
| Mykonos | 72 | 0 | 72 | 91 |
| Maison Asrar | 120 | 12 | 108 | 3 |
| Khadlaj | 116 | 3 | 113 | 29 |
| Bujairami | 142 | 20 | 122 | 2 |
| Paris Corner | 246 | 36 | 210 | 33 |
| Assaf | 140 | 7 | 133 | 8 |
| Al Wataniah | 86 | 2 | 84 | 2 |
| Armaf | 190 | 6 | 184 | 21 |
| French Avenue | 119 | 6 | 113 | 20 |
| Arabiyat Prestige | 118 | 22 | 96 | 22 |
| Gulf Orchid | 23 | 0 | 23 | 0 |
| Swiss Arabian | 32 | 4 | 28 | 3 |
| Games of Spades | 29 | 6 | 23 | 0 |
| Lattafa | 114 | 4 | 110 | 4 |
| Afnan | 87 | 1 | 86 | 4 |
| Aromatix | 12 | 0 | 12 | 0 |
| Maison Alhambra | 207 | 6 | 201 | 22 |
| Zimaya | 76 | 15 | 61 | 15 |
| Al Haramain | 101 | 8 | 93 | 9 |
| **Total** | **2,058** | **186** | **1,872** | **288** |

The remaining three identities in the 2,061-row seed belong to brands outside this twenty-brand requested set. The 288 variants shown above belong to the requested brands; the full seed has 291 variants.

## Mykonos travel-size reconciliation

Mykonos has 72 canonical identities and 91 explicit variant rows. Exactly 18 of those variants are 15 ml travel-size rows. All 18 carry the same evidence URL:

`https://officialmykonos.com/products/mykonos-sansa-edp-travel-size-15ml`

The product page supports the 18 scent options and 15 ml size. It does not state concentration for each selectable scent. Therefore, **all 18 new 15 ml variant rows intentionally have no concentration field**, even when a parent identity has a concentration recorded for a different size. This is a variant-level evidence rule, not missing data to be filled by inference.

The Mykonos audit document has been corrected so the pre-travel-size count of 73 variants is explicitly marked as a historical checkpoint, and the concentration rule is consistent throughout.

## Structural checks on the current seed

The direct JSON reconciliation found:

- Duplicate product IDs: **0**
- Duplicate variant IDs: **0**
- Duplicate brand/canonical-name pairs: **0**
- Orphan variants (variant with no parent product): **0**
- Variant rows without a positive size: **0**
- Variant sizes absent from the parent product's `formats_ml`: **0**
- Family registry entries: **34**

These checks establish structural consistency of the JSON seed. They do **not** prove that every historical or current fragrance worldwide is represented, that every listing-level name is independently verified, or that retailer offers and prices are live.

## CI evidence

- PR #437 catalog-seed validation: [run 42459299922](https://github.com/dalexmon81/ScentHunter/actions/runs/42459299922) — completed successfully.
- PR #439 catalog-seed validation: [run 42495525222](https://github.com/dalexmon81/ScentHunter/actions/runs/42495525222) — completed successfully.
- PR #530 audit regression: [run 42501867011](https://github.com/dalexmon81/ScentHunter/actions/runs/42501867011) — completed successfully.

The #530 run validates the read-only variant coverage audit fix; it is not a substitute for the catalog-seed validation runs above.

## Recommended next work

Do not add another bulk batch based only on the aggregate totals. Prioritize individual product-page evidence for brands with the largest listing-level-only populations, starting with Maison Alhambra, Armaf, Lattafa, Assaf, Khadlaj, Al Wataniah, and Mykonos. Keep listing-level names clearly labeled until individual product pages confirm them. Only create a new variant when its size is explicitly supported, and only populate concentration when evidence applies to that exact variant.

This reconciliation is documentation-only. It does not merge PR #437, #439, or #530 and does not alter `main` or production.
