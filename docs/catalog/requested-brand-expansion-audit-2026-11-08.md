# Requested fragrance catalog expansion — audit 2026-11-08

## Current branch snapshot

Branch: `catalog/brand-expansion-2026-11` (PR #425; keep draft/open).

- Canonical product identities: **949**
- Explicit variant rows: **141**
- Discovery families: **30**
- Newly added in this increment: **2 Al Ambra identities**
- No commercial offers, prices, stock, shipping costs or retailer credentials were added.

Counts were read from the branch's `backend/product_catalog.json` and `backend/family_registry.json` after the Al Ambra additions. Brand counts are canonical identities, not guaranteed exhaustive market coverage.

## Canonical identities currently present by requested brand

| Brand | Canonical identities |
|---|---:|
| Velixir | 28 |
| Mykonos | 72 |
| Maison Asrar | 116 |
| Khadlaj | 36 |
| Bujairami | 4 |
| Paris Corner | 18 |
| Assaf | 21 |
| Al Wataniah | 10 |
| Armaf | 190 |
| French Avenue | 19 |
| Arabiyat Prestige | 3 |
| Gulf Orchid | 10 |
| Swiss Arabian | 31 |
| Games of Spades | 4 |
| Lattafa | 15 |
| Afnan | 47 |
| Aromatix | 12 |
| Maison Alhambra | 203 |
| Zimaya | 70 |
| Al Haramain | 36 |
| Al Ambra | 2 |

## Al Ambra: source-verified increment

Azmara's brand collection exposes exactly two items, both currently marked sold out by that retailer:
- **Secret Adventure** — 100 ml Eau de Parfum; product page: https://azmara-perfumes.com/collections/al-ambra/products/al-ambra-secret-adventure
- **Cecil** — 100 ml Eau de Parfum; product page: https://azmara-perfumes.com/collections/al-ambra/products/al-ambra-cecil

The brand collection is https://azmara-perfumes.com/collections/al-ambra and its parent brand directory shows Al Ambra as a distinct brand with 2 items. The two canonical identities and discovery aliases have been added. No stock or price has been imported; the retailer's sold-out status is not a ScentHunter offer.

## Independent assortment checks — not exhaustive completeness claims

These are current third-party retailer assortment counts and useful cross-checks only. They are not official brand-master counts, may include mixed product types, and must not be treated as a direct completeness denominator.

- Azmara collection directory: Afnan 34, Al Ambra 2, Al Haramain 11, Arabiyat Prestige 45, Armaf 71, French Avenue 140, Gulf Orchid 45, Khadlaj 35, Lattafa 213, Maison Alhambra 50, Maison Asrar 46, Paris Corner 76, Swiss Arabian 60, Zimaya 39. Source: https://azmara-perfumes.com/collections
- Essência Árabe collections: Afnan 17, Al Haramain 6, Al Wataniah 4, Arabiyat Prestige 13, Armaf 40, Bujairami 29, French Avenue 62, Khadlaj 23, Lattafa 124, Maison Alhambra 37, Maison Asrar 22, Mykonos 24, Paris Corner 38, Swiss Arabian 18, Velixir 11, Zimaya 4. Source: https://www.essenciaarabe.com/en/collections
- Sand of Scent product-crawl snapshot: Bujairami 83, Velixir 45, French Avenue 45, Maison Asrar 43, Mykonos 39, Lattafa 22, Armaf 17, Khadlaj 16, Swiss Arabian 12, Arabiyat Prestige 11, Gulf Orchid 6, Assaf 5, Al Haramain 5, Zimaya 4, Afnan 3, Paris Corner 1. Source: https://architectcommerce.com/shops/sandofscent.dk

## Completeness status

**Not complete.** The current branch has a substantial sourced identity set, but many brand counts are materially below independent retailer assortments. Retailer assortment counts are only leads: they differ by country, date, category, and whether collections include gift sets/body products. The official-source pagination audit remains outstanding for every requested brand.

Next extraction must:
1. Capture every official brand catalog page and load-more page through the last result.
2. Separate fragrance identities from body care, home fragrance, accessories and non-perfume products.
3. Reconcile retailer-only products without treating inspired-by references as the original brand.
4. Preserve product-level source URLs and provenance.
5. Add sizes/concentrations/GTINs only from product-level evidence; unknown values stay unknown.
6. Deduplicate identities and retain genuine flankers and variants.
7. Generate a per-brand source-listed/imported/duplicate/excluded/unresolved report.
8. Run all catalog integrity tests and PR workflows on the final branch head.

## Safety

- PR #425 remains draft/open; do not merge.
- PR #424 remains untouched.
- Do not seed or mutate staging/production databases, deploy, activate stores or publish offers.
- Liquid Brun remains the planned real-source ingestion acceptance test after catalog and architecture gates are satisfied.


## Incremental source extraction — 2026-11-08 (Paris Corner + Lattafa)

The official Paris Corner all-products collection reports **255 products**. The rendered public page exposes only a subset per pagination view; pages 1–4 were inspected and the visible perfume identities were added to the canonical catalog with source provenance. The displayed list also includes house sub-labels such as Emir / North Stag; these remain attributed to the Paris Corner house where shown by its own official collection. Product-level concentration, size and variants were not inferred. The visible pages are **not** a complete 255-item extraction, and the audit remains open.

Official source: https://www.pariscornerperfumes.com/collections/all (pagination pages 1–4 inspected).

Lattafa official perfume category exposes current names including Fahad, Khamrah Waha, Sheikh Al Shuyukh Supreme, Jouri, Ana Abiyedh Passion, Ameerat Al Arab Sugar Crown, Mishlah, Angham Second Song, Maahir Honor, Dalal, Yara Elixir, Asad Elixir and Musamam Black Intense. Most were already present; **Musamam Black Intense** was added where missing. Source: https://lattafa.com/product-category/perfumes/ .

### Current incremental totals
- Canonical identities: 1,031
- Explicit variant rows: 141 (unchanged; no unsupported variants inferred)
- Paris Corner identities: 99
- Lattafa identities: 16
- Family registry: synchronized with the canonical identities for these two brands.

Important: the official Lattafa page's pagination is not fully verified, and the Paris Corner 255-item collection was not fully extracted. Do not mark either brand complete based on this increment. Continue page-by-page, capture all results and filter non-perfume products before claiming completion.


## Registry integrity reconciliation — 2026-11-08

A full cross-check found 203 canonical catalog identities that were not yet represented in the discovery family registry. These have now been synchronized into their existing `family_id` groups (and one missing family group was created). Final structural checks on this snapshot:
- 1,031 canonical products
- 141 variant rows
- 31 discovery families
- 0 duplicate product IDs
- 0 duplicate variant IDs
- 0 orphan variant rows
- 0 canonical products missing from the discovery registry

This is an important integrity repair, not proof that the requested brand assortments are complete. The source-coverage audit remains open.


## Gulf Orchid official-catalog increment — 2026-11-08

Added 10 fragrance identities from the brand's official perfume collection and product pages:
Vanilla Addiction, Mango Ice, Cotton Candy Musk, Tahara Vanilla Musk, Sweet Heaven 20ML, Pink Marshmallow, Coco Blanco, Exotic Oud, Vanilla Latte, Cookie Bite.

Each entry records its official product URL as source evidence. Only the identity is recorded; concentration and bottle size are not generalized from names unless later verified as a specific variant. Gift sets, body mists, hair mists, room fragrances and other non-perfume categories were not imported as perfumes.

Official source collection: https://shop-gulforchid.com/collections/gulf-orchid-perfume . Product pages are linked from the official collection. Gulf Orchid catalog count on this branch is now 20.

Maison Asrar cross-check: official all-products page reports 130 products, but its visible first-page listing exposes only a subset and the page includes non-perfume categories in the navigation. Its Royal Collection contains 9 products; all 9 names are already present in the catalog. The separate Maison Asrar catalog remains subject to a full pagination/product-type audit; do not equate the total 130 with 130 perfume identities.

Velixir cross-check: the official range is reported as 28 perfumes; the current catalog already contains 28 Velixir identities. The opened full-range listing is an independent reseller's reproduction of brand-site information, so it is used as a cross-check rather than direct official source proof. Source: https://velixirperfumes.eu/perfumes/ .


## Aromatix line verification — 2026-11-08

The Shop Aromatix signature collaboration page identifies a ten-fragrance Aromatix X French Avenue collection: Teas Me, Frostbite, Naughty Dates, Sun Kissed, Forbidden Fruit, Magnetiq, Platine Blanc, X Xandal, Royal Taboo and Carnal Desire. All ten identities are already present in the catalog under the Aromatix brand; no duplicate rows were added. The shop's collection listing reports 12 products because it also contains two Summer Vibes boxed sets; these are not added as standalone perfume identities. Existing Aromatix catalog count remains 12 (the ten signature fragrances plus two other entries already present).

Sources: https://shoparomatix.com/pages/aromatic-collection and https://shoparomatix.com/collections/aromatix-x-french-avenue . This verifies the collaboration line only; it does not establish a broader independent Aromatix manufacturer range.

## Latest integrity snapshot
- 1,041 canonical identities
- 141 variant rows
- 31 discovery families
- Gulf Orchid: 20 identities
- Aromatix: 12 identities
- Paris Corner: 99 identities
- Lattafa: 16 identities
- 0 duplicate product IDs; 0 duplicate variant IDs; 0 orphan variants; 0 canonical products missing from the registry.


## Paris Corner official collection pagination increment — 2026-11-08

Inspected the official all-products collection pagination (pages 1–8; the collection header reports 255 products). Added **79 additional product identities** that were visible in the inspected pages and missing from our catalog, with the page URL recorded as source evidence. The entries include product names under the Paris Corner house's official sub-labels (for example Emir, North Stag, Khair, Taskeen, Qissa and Ministry of Oud). Product identities are kept at the brand/house level as listed in the official Paris Corner umbrella collection. Do not infer EDP/extrait, sizes, variants, GTIN, stock or price from a name alone.

Official pages inspected:
- https://www.pariscornerperfumes.com/collections/all
- https://www.pariscornerperfumes.com/collections/all?page=2
- https://www.pariscornerperfumes.com/collections/all?page=3
- https://www.pariscornerperfumes.com/collections/all?page=4
- https://www.pariscornerperfumes.com/collections/all?page=5
- https://www.pariscornerperfumes.com/collections/all?page=6
- https://www.pariscornerperfumes.com/collections/all?page=7
- https://www.pariscornerperfumes.com/collections/all?page=8

The current catalog contains **178 Paris Corner house-level identities**. This is still not a verified exhaustive import of the 255-product collection: the collection includes sub-labels and possible non-perfume/set items, and page-by-page classification of all 255 entries plus product-type verification is still required. The 178 figure is a current catalog count, not a completion claim.

### Latest integrity snapshot
- 1,120 canonical identities
- 141 explicit variant rows
- 31 discovery families
- Paris Corner: 178 identities in catalog and registry
- 0 duplicate product IDs; 0 duplicate variant IDs; 0 orphan variant rows; 0 canonical products missing from discovery registry
