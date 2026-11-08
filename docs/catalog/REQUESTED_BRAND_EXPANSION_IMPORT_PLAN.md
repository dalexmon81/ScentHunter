# Catalog expansion import plan — requested fragrance houses

## Scope and existing catalogue audit

The current central catalogue on `main` contains 1,389 product identities and 61 brands. These requested names already exist in its brand table: Afnan, Armaf, French Avenue, Khadlaj, Lattafa, Maison Alhambra. Existing product counts at audit time: Afnan 75, Armaf 13, Khadlaj 3, Lattafa 3, French Avenue 118, Maison Alhambra brand record present (product count not included here). Do not replace or duplicate them; expand by verified identity and audit current coverage first.

The family registry already contains an `aromatix_french_avenue` family with 12 identities; metadata says 12 verified identities: Carnal Desire, Forbidden Fruit, Frostbite, Magnetiq, Naughty Dates, Ora, Platine Blanc, Royal Taboo, Roza, Sun Kissed, Teas Me, X Xandal. Preserve these and avoid duplicates.

## Research sources

| Requested name | Evidence and source | Ingestion note |
|---|---|---|
| Velixir | Official collection shows 30 products. | Enumerate pages/products and their explicit sizes/concentration. https://velixirparfums.store/collections/all |
| Mykonos | Official collections page lists separate 100 ml and 50 ml collections; official brand story says Indonesian perfume house. | Resolve brand identity to Mykonos (not Greek location) and enumerate SKUs. https://officialmykonos.com/collections ; https://mykonosperfumes.eu/pages/our-story |
| Maison Asrar / Royal Collection | European perfume directory enumerates 116 scents; official Royal Collection page lists 9 products. | Use official Royal Collection as first-party subset; use EU directory only as secondary provenance. https://maisonasrar.com/collections/royal-collection ; https://maisonasrarperfumes.eu/fr/perfumes/ |
| Khadlaj | Official collections directory exposes extensive named collections and counts. | Existing brand and 3 product identities; source-driven delta import required. https://khadlaj-perfumes.com/collections |
| Bujairami | Third-party guide reports 1,222 names on brand list as of 2026-11-05; guide covers 1,207. | Clearly mark third-party provenance; do not state the guide is official. https://bujairamiperfumes.eu/ |
| Paris Corner | Official all-products catalogue. | Filter perfumes vs home/body/gift products. https://www.pariscornerperfumes.com/collections/all |
| Assaf | Catalogue enumerates 140 scents. | Secondary source; mark provenance and validate source pages where possible. https://assafperfumes.eu/perfumes/ |
| Al Wataniah | Official product site shows Classic Collection and current releases. | Paginate official range. https://www.alwataniah.com/ |
| Armaf | Official All Fragrances catalogue shows 248 Eau de Parfum products plus other formats. | Existing brand and 13 product identities; delta import. Exclude body care/deodorants from perfume identities. https://armaf.com/collections/all-perfumes |
| French Avenue | Official site exposes product collections including Aromatix Collection. | Existing brand and 118 identities. Already contains verified French Avenue catalog expansion; perform missing-item diff, do not blindly append. https://frenchavenue.com/products/ |
| Arabiyat Prestige | Official product catalogue lists named products and collections. | Separate Arabiyat vs Arabiyat Prestige identities; do not merge. https://arabiyatprestige.com/ |
| Gulf Orchid | Official collection directory exposes many fragrance collections. | Restrict to perfume SKUs; separate mists, deodorants and home fragrance. https://shop-gulforchid.com/collections |
| Swiss Arabian | Exhaustive source not verified in this research pass. | Keep pending source discovery; no guessed seed. |
| Games of Spades (Jo Milano Paris) | Brand retailer collection lists 77 items, including Full House, Opal, Moon, Emerald, Boston, Double Bonus and Bonus, plus gift sets. | Keep Games of Spades as line/family under Jo Milano Paris, not separate manufacturing brand. Model gift sets separately. https://www.jperfumeusa.com/collections/game-of-spade |
| Lattafa | Retail catalogue lists 283 products across Lattafa / Lattafa Pride and non-perfume formats. | Existing brand but only 3 canonical identities at audit time. Official domain not verified from this result; use catalogue as secondary evidence and prioritize first-party source. https://www.lattafa-usa.com/collections/all |
| Afnan | Official site shows lines/collections 9AM/9PM, Supremacy, Bouquet, Historic, Kiaana, Modest, Mirsaal, Lynked, Tribute, Turathi, Edict, Rare and more. | Existing brand and 75 identities; compare official enumeration with catalog to produce a delta. https://afnan.com/ |
| Aromatix | Retail collection lists Aromatix X French Avenue items; repo already has 12 identities. | Model as a collaboration/line under French Avenue unless authoritative brand documentation proves an independent brand. https://shoparomatix.com/collections/all-products |
| Maison Alhambra | Existing brand record in the catalogue; exhaustive authoritative source not verified in this research pass. | Audit existing products; queue official source discovery before further additions. |
| Zimaya | Exhaustive authoritative source not verified in this research pass. | Pending source discovery; do not guess product names. |
| Al Haramain | Official EU collection lists 198 items over 5 pages. First page includes Junoon, Amber Oud Ruby Edition, Amber Oud Gold Edition Extreme, L'Aventure Grapefruit/Iris/Ciel, Detour Noir and more. | Paginate all five pages; separate size/concentration variants. https://shop.alharamainperfumes.com/eu/collection.html |

## Required ingestion behavior

- Treat "all" as a source-driven, paginated enumeration, never a manually assembled sample represented as complete.
- Save raw source snapshots/fixtures and per-product provenance (source URL, source type, observed/retrieved time, source hash/version).
- Official brand/collection pages are preferred. Authorized retailer next; independent fragrance directories only as clearly flagged fallback.
- Exclude gift sets, discovery kits, miniatures, samples, oils, deodorants, home fragrance, body mist/body care unless modeled as separate explicit product types.
- Do not infer GTIN, concentration, size, audience, stock, price, image URL or availability from names/images alone. Unknown remains null; ambiguous identities go to review.
- Do not merge a perfume with its inspiration/dupe reference. Do not use inspired-by mappings as brand aliases.
- Deduplicate by exact GTIN when verified. Otherwise use normalized brand + canonical name + concentration + gender/audience only where the source explicitly distinguishes it. Link size/tester/refill/gift-set differences as distinct variants.
- Do not add retailer offers. This branch is catalogue enrichment only; it must not affect the Liquid Brun live-offer acceptance test.

## Current branch safety

Working branch: `catalog/expanded-fragrance-brands`, created from `main`.
A research note has been committed on this branch. PR #424 remains open, draft, and unmerged. No production configuration or traffic was changed.

## Next execution steps

1. Materialize/parse the full catalogue using a GitHub blob (the contents API may truncate large files).
2. Fetch complete product and variant schema consumers/import tooling.
3. Enumerate product pages for each first-party source and create machine-readable source fixtures.
4. Generate a deduplicated delta JSON with known fields only; keep unresolved brands/items in a separate review report.
5. Run structural checks: duplicate canonical identities, orphan variants, duplicate IDs, invalid product references, unverified metadata.
6. Add CI validation and review the exact before/after counts before proposing a PR.
7. Do not merge or deploy without review.
