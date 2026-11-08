# Catalog head validation — 2026-11-08

## Exact revision inspected
- Branch: `catalog/complete-brand-expansion-2026-11`
- Commit: `71b3c3929665c6f25c238cd12eb990b7ee33732b`
- Pull request: #426 (open, draft, unmerged)
- This is a structural audit of the exact branch snapshot. It is not a CI result and not a production import.

## Canonical seed snapshot
- Canonical product identities: **1,726**
- Explicit variant rows: **192**
- Family registry groups: **34**
- Identity evidence: **106 source_verified_name**, **1,620 source_listed_name**
- Products missing source_url: **0**
- Duplicate product IDs: **0**
- Duplicate variant IDs: **0**
- Orphan variants: **0**
- Duplicate brand + canonical-name pairs: **0**

A `source_verified_name` indicates an individual product-detail source. A `source_listed_name` indicates a collection/listing discovery source. Listing-backed names are not proof of a specific SKU, concentration, size, GTIN or current commercial availability.

## Counts by requested brand / line

| Brand / line | Canonical identities |
|---|---:|
| Velixir | 28 |
| Mykonos | 72 |
| Maison Asrar | 120 |
| Khadlaj | 55 |
| Bujairami | 142 |
| Paris Corner | 243 |
| Assaf | 21 |
| Al Wataniah | 10 |
| Armaf | 190 |
| French Avenue | 117 |
| Arabiyat Prestige | 118 |
| Gulf Orchid | 20 |
| Swiss Arabian | 32 |
| Games of Spades | 29 |
| Lattafa | 91 |
| Afnan | 87 |
| Aromatix | 12 |
| Maison Alhambra | 203 |
| Zimaya | 72 |
| Al Haramain | 61 |

Counts describe this branch snapshot, not every historical, regional or currently marketed fragrance. Giorgio Armani (1) and Al Ambra (2) are separate labels outside the 20 requested brands. Do not merge Al Ambra with Maison Alhambra.

## Registry and identity reconciliation
- All canonical products have a source_url and the structural audit found no duplicate product/variant IDs or orphan variants.
- The family registry contains 34 groups. The dedicated `french_avenue_genesis` family remains separate from Liquid Brun Limited Edition.
- `lattafa_asad` remains limited to Asad, Asad Zanzibar, Asad Bourbon and Asad Elixir.
- Narrow Khadlaj sub-lines, including Shiyaaka and La Fede, remain distinct rather than being flattened into the parent family.
- The accent-only Giorgio Armani Acqua di Gio / Acqua di Giò Profondo identity is represented once, retaining its size variants and source aliases.
- Maison Asrar Lock & Key: Plot Twist, Love Key and Unsolved Mystery are present as individual canonical identities, with explicit 100 ml EDP variants and corresponding registry records. Their cited product pages are Gulf Orchid store product pages; this is retailer product-level evidence, not Maison Asrar's own domain.
- Khadlaj La Fede: three individually verified identities are canonical — Intoxicate Mystique (100 ml Extrait de Parfum), Celebrity Crush (100 ml EDP) and Celebrity Fame (100 ml EDP). The registry retains 36 discovery names; the other 33 remain registry-only and have not been bulk-imported.
- Arabiyat Prestige: Marwa Extrait is separate from Marwa EDP, with a 60 ml Extrait de Parfum variant and GTIN `6295156402103` mapped to that exact variant. Mahd Al Dhahab Extrait is individually verified with a 60 ml Extrait variant. The existing catalog identities for Gelato Raspberry Ripple and Gelato Black Currant Lolly have individual MyPerfumes Europe product-page provenance.

## CI status at this exact head
- The PR-triggered workflow-run lookup for `71b3c3929665c6f25c238cd12eb990b7ee33732b` returned no runs.
- The combined commit-status lookup returned no status checks.
- Therefore CI is **not verified on this exact head**. Do not infer a pass from earlier successful runs.
- The catalog workflow currently lists **22 test modules**, including `test_maison_asrar_lock_and_key`, `test_khadlaj_la_fede`, `test_arabiyat_prestige_extrait` and `test_arabiyat_prestige_marwa_extrait`.
- `test_arabiyat_prestige_official_store` is not currently in the workflow. It expects official-store provenance and explicit size/concentration variants for a wider set of names; do not enable it until each expected product and variant is reconciled against the current seed and evidence.
- A separate deployment/pilot workflow status is not a catalog validation result. This work did not dispatch a deployment or change production resources.

## Remaining work
1. Reconcile the Arabiyat Prestige official-store regression against current product-level evidence and exact variant rows before adding it to CI.
2. Continue product-page verification of the 1,620 listing-backed identities; do not infer missing size, concentration, GTIN or SKU values.
3. Keep PR #426 draft and unmerged; keep PR #424 separate. No production import, retailer authorization, deployment, live offers, prices or stock are included.
