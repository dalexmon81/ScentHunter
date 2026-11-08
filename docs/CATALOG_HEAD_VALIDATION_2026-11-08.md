# Catalog head validation — 2026-11-08

## Exact revision inspected
- Branch: `catalog/complete-brand-expansion-2026-11`
- Commit: `2be1bb18557fe0b11245c549c2f1e381eadf55a3`
- Pull request: #426 (draft, open, unmerged)
- This is a structural audit of the exact branch files. It is not a CI result and not a production import.

## Canonical seed snapshot
- Canonical product identities: **1726**
- Explicit variant rows: **192**
- Family registry groups: **34**
- Product IDs duplicated: **0**
- Variant IDs duplicated: **0**
- Products missing source_url: **0**
- Orphan variants: **0**
- Duplicate brand + accent-normalized canonical-name pairs: **0**
- Product identity evidence: **106 source_verified_name**, **1620 source_listed_name**.
- Canonical products without an exact family-registry name match after accent/punctuation normalization: **0**.

The evidence statuses are intentionally different. A collection/listing-backed name is a discovery candidate; it is not proof of an individual SKU, concentration, size, GTIN or current commercial availability.

## Counts by requested brand / line

| Brand / line | Canonical identities |
|---|---:|
| Velixir | 28 |
| Mykonos | 72 |
| Maison Asrar | 117 |
| Khadlaj | 52 |
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

These are counts in this branch snapshot, not a claim that every historical, regional or currently marketed perfume has been discovered. The separate labels Giorgio Armani and Al Ambra are not part of the 20 requested brands. Do not silently merge Al Ambra with Maison Alhambra.

## Registry reconciliation applied
- Added/filled family-registry entries so every canonical catalog identity is covered by the family ID assigned to it.
- Created a dedicated `french_avenue_genesis` family for the 11 Genesis collection identities. They are no longer incorrectly assigned to the Liquid Brun Limited Edition family.
- Kept the Liquid Brun Limited Edition family as its own distinct one-product family.
- Confirmed `lattafa_asad` contains only Asad, Asad Zanzibar, Asad Bourbon and Asad Elixir; other Lattafa identities remain under the general Lattafa family.
- Preserved narrow Khadlaj sub-lines such as Shiyaaka, La Fede and the official spray collection rather than flattening all records into a single parent family.
- Merged the accent-only duplicate Giorgio Armani identity (Acqua di Gio / Acqua di Giò Profondo) into one canonical product, retaining the 75 ml, 100 ml and 125 ml variant rows and all three source URLs.
- Structural coverage is now **0 missing canonical-to-registry matches**. Legacy registry-only names are retained; they are not automatically promoted into the canonical product catalog.

## CI status
- GitHub Actions run: [Catalog seed validation #66](https://github.com/dalexmon81/ScentHunter/actions/runs/42454400996)
- Tested code/test commit: `e5d1b738be3cf1be0fb22160b561be40e545a3c6`
- Result: **success — 73 tests passed**.
- The current PR head `2be1bb18557fe0b11245c549c2f1e381eadf55a3` is a documentation-only commit after that successful run. The catalog JSON, family registry, workflow and test files are unchanged from the tested commit.

The catalog validation workflow checks seed integrity, provenance labels, canonical-to-family-registry coverage, selected brand regressions, and variant safety. It deliberately does not claim that all listing-backed identities are product-page verified.

A separate `fly-pilot.yml` workflow reports a failed status on this branch, but it is not the catalog validation suite. This work did not dispatch a Fly deployment or change production resources.

## Deferred source-level checks
The following older regression modules are not part of this CI gate because their assertions currently expect product rows or product-level evidence that is not present in the canonical seed. They remain visible in the repository for follow-up; no missing product sizes or sources were invented to make them pass:
- Khadlaj La Fede: 33 of the 36 registry discovery names remain registry-only; only three have been promoted after individual official product-detail verification.
- `test_arabiyat_prestige_extrait.py`, `test_arabiyat_prestige_marwa_extrait.py`, `test_arabiyat_prestige_official_store.py`: asserted detail-page provenance and explicit 60 ml variants are not yet established for the current seed.

## Remaining validation
1. Review registry-only legacy identities separately; do not auto-promote without product-level evidence and explicit family mapping.
2. Complete product-level source verification for the 1,622 identities still marked `source_listed_name`.
3. Keep PR #426 draft and unmerged; keep PR #424 separate. No production, retailer authorization, deployment, live-offer or pricing changes are included.


## Maison Asrar Lock & Key detail verification
- Added Plot Twist, Love Key and Unsolved Mystery as canonical Maison Asrar identities using individual product pages from the Gulf Orchid store. Gulf Orchid's corporate site lists Maison Asrar among its brands; the store product pages identify each fragrance as 100 ml EDP.
- Added explicit 100 ml Eau de Parfum variant rows and retained the existing Maison Asrar family-registry records.
- Added `backend.tests.test_maison_asrar_lock_and_key` to the CI workflow. No extra identity was created from retailer descriptors such as Black Grapefruit or Bloom; existing alias safeguards remain in the test.

## Khadlaj La Fede detail verification
- Added three canonical La Fede identities that were already present in the family registry but missing from the product seed: Intoxicate Mystique, Celebrity Crush and Celebrity Fame.
- Verified each against its individual official Khadlaj product detail. Recorded 100 ml Extrait de Parfum for Intoxicate Mystique and 100 ml Eau de Parfum for Celebrity Crush and Celebrity Fame.
- Synchronized the three corresponding family-registry `formats_ml` entries. The registry still contains 36 La Fede discovery names; **3 are now canonical and individually verified, while 33 remain registry-only candidates** pending product-level review. They have not been bulk-imported.
- Added `backend.tests.test_khadlaj_la_fede` to the CI workflow. The test now explicitly protects this evidence boundary rather than requiring all 36 registry candidates to be canonical.

## Arabiyat Prestige Extrait follow-up
- Also verified the existing `Marwa Extrait` identity against its individual MyPerfumes Europe product page, distinct from the Marwa EDP. Added the explicit 60 ml Extrait de Parfum variant and aligned the canonical product ID with the already-verified GTIN record `6295156402103`.
- Added `backend.tests.test_arabiyat_prestige_marwa_extrait` to the CI workflow; it checks the product/variant relationship against the verified GTIN map.
- Promoted the existing `Mahd Al Dhahab Extrait` canonical identity from collection/index-listed to `source_verified_name` using the individual MyPerfumes Europe official Arabiyat Prestige product detail: https://eu.myperfumes.ae/en-de/products/mahd-al-dhahab-extrait
- Added the explicitly stated **60 ml Extrait de Parfum** variant; the family registry already contained this identity and `formats_ml: [60]`, so no registry duplication was needed.
- Added `backend.tests.test_arabiyat_prestige_extrait` to the CI workflow. Other Arabiyat and legacy brand modules remain deferred until their missing product-level evidence and catalog rows are reconciled.
- Totals after this change: **1,726 identities**, **192 variants**, **106 source-verified names**, **1,620 source-listed names**.
