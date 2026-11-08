# Requested fragrance catalog scope — 2026-11-08

## Audit result

The starting catalog branch already contains these canonical fragrance identity counts. These are existing record counts, not a claim of complete worldwide/current SKU coverage.

| Brand / line | Existing identities |
|---|---:|
| Velixir | 28 |
| Mykonos | 72 |
| Maison Asrar | 120 |
| Khadlaj | 116 |
| Bujairami | 142 |
| Paris Corner | 245 |
| Assaf | 140 |
| Al Wataniah | 86 |
| Armaf | 190 |
| French Avenue | 117 |
| Arabiyat Prestige | 118 |
| Gulf Orchid | 23 |
| Swiss Arabian | 32 |
| Games of Spades | 29 |
| Lattafa | 114 |
| Afnan | 87 |
| Maison Alhambra | 203 |
| Zimaya | 72 |
| Al Haramain | 101 |

## Research sources checked

- Velixir range: https://velixirperfumes.eu/families/
- Mykonos official collections: https://officialmykonos.com/collections
- Maison Asrar Royal Collection: https://maisonasrar.com/collections/royal-collection
- Maison Asrar all products: https://maisonasrar.com/collections/all
- Aromatix x French Avenue collection: https://shoparomatix.com/pages/aromatic-collection
- Assaf independent range index: https://assafperfumes.eu/perfumes/
- Lattafa Europe all fragrances: https://lattafaparfum.eu/de-de/collections/all
- Armaf all perfumes: https://armaf.com/collections/all-perfumes
- Zimaya products: https://zimayaperfumes.com/collections/all
- Al Wataniah official collections: https://www.alwataniah.com/

## Aromatix line to reconcile

The Aromatix x French Avenue official collection page names ten fragrances:
1. Teas Me
2. Frostbite
3. Naughty Dates
4. Sun Kissed
5. Forbidden Fruit
6. Magnetiq
7. Platine Blanc
8. X Xandal
9. Royal Taboo
10. Carnal Desire

Do not treat these as evidence that all French Avenue products belong to Aromatix. Preserve the collaboration/line relationship and avoid duplicate canonical identities.

## Evidence and data-quality policy

1. Normalize brand/name pairs and reconcile aliases before adding products.
2. Collection-only identities remain `source_listed_name`; only an individual product-detail page supports `source_verified_name`.
3. Never infer concentration, size, GTIN/EAN, SKU, availability, price, shipping or retailer offers.
4. Keep perfumes separate from body mists, room sprays, oils, bakhoor, gift sets, discovery kits and non-fragrance products unless separately modeled.
5. Retain exact source URLs and collection identifiers, plus a checked-at date.
6. Add regression tests for newly imported collections and structural integrity (unique product IDs, unique normalized brand/name pairs, unique variant IDs, no orphan variants, family-registry coverage).
7. Do not add prices/offers/stock or affiliate data as part of catalog seeding.

## Important completeness limits

- Existing counts above are taken from the catalog branch being audited. They do not prove that every item ever released by each brand is present.
- Assaf's 140 names are supported by an independent range index, not all official product-detail pages; keep the existing evidence tier unless an official page is verified.
- Maison Asrar's Royal Collection source currently displays nine products, while its all-products collection shows a larger multi-category listing. Deduplicate overlap and exclude non-perfume categories.
- Mykonos official store collection pages are the preferred source; secondary retailer descriptions should not be used to claim the entire official range.

## Safety / workflow

This is an audit and research specification only. It must be applied as a new, reviewable catalog PR stacked on the catalog expansion branch. Do not change `main`, production data/configuration, deployments, live traffic, or PR #424. PR #437 remains open and unmerged until its own review/validation path is completed.
