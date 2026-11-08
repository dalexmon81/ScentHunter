# Catalog head validation — 2026-11-08

## Exact revision inspected
- Branch: `catalog/complete-brand-expansion-2026-11`
- Commit: `0c2896cca589671003f57ec84e6f1ba77dc602b6`
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
- GitHub Actions run: [Catalog seed validation #51](https://github.com/dalexmon81/ScentHunter/actions/runs/42454300386)
- Exact tested commit: `7bea4c4f8702a3fe52c806f04cdac388aa78b93e`
- Result: **success** — 73 tests passed.

The CI suite now checks seed integrity, provenance labels, canonical-to-family-registry coverage, selected brand regressions, and variant safety. It deliberately does not claim that all listing-backed identities are product-page verified.

## Deferred source-level checks
The following older regression modules are not part of this CI gate because their assertions currently expect product rows or product-level evidence that is not present in the canonical seed. They remain visible in the repository for follow-up; no missing product sizes or sources were invented to make them pass:
- `test_khadlaj_la_fede.py`: 36 La Fede names exist in the family registry but are not yet canonical product rows.
- `test_maison_asrar_lock_and_key.py`: Plot Twist, Love Key and Unsolved Mystery do not yet have the asserted canonical product and 100 ml variant records.
- `test_arabiyat_prestige_extrait.py`, `test_arabiyat_prestige_marwa_extrait.py`, `test_arabiyat_prestige_official_store.py`: asserted detail-page provenance and explicit 60 ml variants are not yet established for the current seed.

## Remaining validation
1. Review registry-only legacy identities separately; do not auto-promote without product-level evidence and explicit family mapping.
2. Complete product-level source verification for the 1,622 identities still marked `source_listed_name`.
3. Keep PR #426 draft and unmerged; keep PR #424 separate. No production, retailer authorization, deployment, live-offer or pricing changes are included.
