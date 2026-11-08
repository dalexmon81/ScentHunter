# Catalog head validation — 2026-11-08

## Exact revision inspected
- Branch: `catalog/complete-brand-expansion-2026-11`
- Commit: `9dea6b44da2b3805378d55598067be18ef381dd6`
- Pull request: #426 (draft, open, unmerged)
- This is a read-only structural inspection of the exact branch files. It is not a CI result and not a production import.

## Canonical seed snapshot
- Canonical product identities: **1721**
- Explicit variant rows: **184**
- Brand labels in the product seed: **22**
- Product IDs duplicated: **0**
- Variant IDs duplicated: **0**
- Products missing source_url: **0**
- Orphan variants: **0**
- Duplicate brand + canonical-name pairs: **0**
- Product identity evidence: **99 source_verified_name**, **1622 source_listed_name**.

The two evidence statuses are intentionally different. A collection/listing-backed name is a discovery candidate; it is not proof of an individual SKU, concentration, size, GTIN or current commercial availability.

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

These are counts in this branch snapshot, not a claim that every historical, regional or currently marketed perfume has been discovered. Existing rows include some separate line/brand classifications; the catalog also has two additional labels outside the request: Giorgio Armani and Al Ambra. Do not silently merge Al Ambra with Maison Alhambra.

## Family registry reconciliation — blocker

A comparison of `family_id` and canonical names in `backend/product_catalog.json` against the family registry found **27 family IDs with a count or membership discrepancy**. Examples include:
- `maison_asrar_catalog`: catalog 117, registry 119; 1 catalog names absent from registry, 3 registry names absent from catalog
- `paris_corner_catalog`: catalog 243, registry 252; 22 catalog names absent from registry, 31 registry names absent from catalog
- `khadlaj_catalog`: catalog 44, registry 51; 11 catalog names absent from registry, 18 registry names absent from catalog
- `bujairami_catalog`: catalog 142, registry 5; 137 catalog names absent from registry, 0 registry names absent from catalog
- `al_wataniah_catalog`: catalog 10, registry 95; 0 catalog names absent from registry, 85 registry names absent from catalog
- `french_avenue_catalog`: catalog 94, registry 10; 84 catalog names absent from registry, 0 registry names absent from catalog
- `arabiyat_prestige_catalog`: catalog 118, registry 53; 74 catalog names absent from registry, 9 registry names absent from catalog
- `gulf_orchid_catalog`: catalog 20, registry 10; 10 catalog names absent from registry, 0 registry names absent from catalog
- `afnan_catalog`: catalog 87, registry 47; 40 catalog names absent from registry, 0 registry names absent from catalog
- `lattafa_catalog`: catalog 86, registry 14; 74 catalog names absent from registry, 2 registry names absent from catalog
- `zimaya_catalog`: catalog 72, registry 73; 0 catalog names absent from registry, 1 registry names absent from catalog
- `al_haramain_catalog`: catalog 61, registry 37; 25 catalog names absent from registry, 1 registry names absent from catalog
- `games_of_spades_catalog`: catalog 29, registry 30; 0 catalog names absent from registry, 1 registry names absent from catalog
- `maison_alhambra_catalog`: catalog 203, registry 191; 12 catalog names absent from registry, 0 registry names absent from catalog
- `giorgio_armani_catalog`: catalog 2, registry 0; 2 catalog names absent from registry, 0 registry names absent from catalog
- `mykonos_catalog`: catalog 72, registry 62; 10 catalog names absent from registry, 0 registry names absent from catalog
- `armaf_catalog`: catalog 190, registry 39; 151 catalog names absent from registry, 0 registry names absent from catalog
- `lattafa_asad`: catalog 5, registry 45; 1 catalog names absent from registry, 41 registry names absent from catalog

This is not safe to repair by blindly copying product rows: some registry families are intentionally narrower line groupings (for example La Fede, Shiyaaka, Lattafa Asad and Aromatix/French Avenue), while the canonical seed groups additional products under broader family IDs. The exact ownership and alias semantics must be reconciled family by family before editing the registry. Until then, do not claim catalog/registry parity or import this seed into a persistent database.

## CI status at inspection
GitHub returned no workflow runs and no commit status checks for this exact head. Therefore CI is **pending / not verified**, not green.

## Required next actions
1. Reconcile the family registry with an explicit mapping policy for parent brands, sub-lines and aliases; preserve intentional narrow families.
2. Extend the seed validation workflow to execute the structural integrity suite and the requested-brand regression suites.
3. Run CI on the resulting head and fix any failures.
4. Complete paginated, product-level source diffs for brands still supported only by collection listings.
5. Keep PR #426 draft and unmerged; keep PR #424 separate. No production, retailer authorization, deployment, live-offer or pricing changes are included.
