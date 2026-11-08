# Catalog head validation — 2026-11-08

## Exact revision inspected
- Branch: `catalog/complete-brand-expansion-2026-11`
- Commit: `8aed146e83a4a0f6f231a2c03897f5a4ebfe8094`
- Pull request: #426 (draft, open, unmerged)
- This is a structural audit of the exact branch files. It is not a CI result and not a production import.

## Canonical seed snapshot
- Canonical product identities: **1720**
- Explicit variant rows: **184**
- Family registry groups: **34**
- Product IDs duplicated: **0**
- Variant IDs duplicated: **0**
- Products missing source_url: **0**
- Orphan variants: **0**
- Duplicate brand + accent-normalized canonical-name pairs: **0**
- Product identity evidence: **98 source_verified_name**, **1622 source_listed_name**.
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
The available GitHub integration returned no pull-request workflow run and no commit status check for this exact head at the time of this report. This does not prove that no push-triggered Actions run exists, because the run-list integration only exposes pull-request-triggered runs. CI for this exact head is therefore **not verified**, not green.

## Remaining validation
1. Obtain a real GitHub Actions result for this head and fix any failures.
2. Review any registry-only legacy identities separately; do not auto-promote without source evidence and explicit family mapping.
3. Complete product-level source verification for the identities still marked `source_listed_name`.
4. Keep PR #426 draft and unmerged; keep PR #424 separate. No production, retailer authorization, deployment, live-offer or pricing changes are included.
