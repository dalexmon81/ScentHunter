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


## Bujairami and Khadlaj official-source increment — 2026-11-08

### Bujairami
The official Bujairami UAE all-products collection reports 117 products. Pages 1–4 were inspected and **117 named fragrance products** were added to the canonical catalog, each with the corresponding page URL recorded as source evidence. The entries include Bujairami's own inspired-fragrance range and original creations as labelled by the shop. These are Bujairami-branded products; the inspired-by reference names are not treated as separate products or brands. The existing four Bujairami entries from the EU domain remain distinct and were not duplicated. Current Bujairami catalog count: **121** (117 UAE range entries + 4 pre-existing EU range entries). Pages inspected:
- https://bujairami.ae/collections/all
- https://bujairami.ae/collections/all?page=2
- https://bujairami.ae/collections/all?page=3
- https://bujairami.ae/collections/all?page=4

### Khadlaj
Added eight missing named fragrances from the official Khadlaj new-launch collection, with direct product-page provenance: Onyx Galaxy, Muse, Sueno, Saraya, Zayaan Silver, Qarar, Ihthiraam and Icon. The collection page reports 89 products, but only the first 12 were visible in the captured listing; therefore the eight additions are an incremental import, not a complete new-launch audit. No unsupported variants or offers were created.
Official source: https://khadlaj-perfumes.com/collections/khadlaj-new-launches . Product pages are recorded individually in the catalog.

### Latest integrity snapshot
- 1,245 canonical identities
- 141 explicit variant rows
- 31 discovery families
- Bujairami: 121 identities (117 from UAE official collection plus 4 pre-existing EU range identities)
- Khadlaj: 44 identities
- 0 duplicate product IDs; 0 duplicate variant IDs; 0 orphan variants; 0 canonical products missing from discovery registry
- 0 duplicate canonical names within Bujairami and Khadlaj

Coverage remains incomplete for Khadlaj's 89-item new-launch collection and for the broader requested brand set. The counts above are not claims that every fragrance ever released by either brand is represented.


## Further Khadlaj and French Avenue extraction — 2026-11-08

Khadlaj's official new-launch page pagination was inspected through page 2. Added four more missing named perfumes visible there: Strawberry Shake, Nafais Magrib, Mansion and Peach Velvet. Current Khadlaj catalog count: **48**. The collection contains 89 items and pagination/load-more continues beyond the inspected pages; it is not complete.

French Avenue's official all-products collection reports **142 products**. The visible first-page products were inspected and 10 missing fragrance identities were added: Spectre Wraith, Cocoa Morado, Amber Empire, Dusk Till Dawn, Royal Blend Sequoia, Noble Cedar, Jasmere, Atlantis Extrait, Ambroise Pour Femme, Aether and Imperial Ocean. Current French Avenue catalog count: **30**. This is a partial page-level extraction, not a complete import of all 142 entries. The page has product filters and a load-more control; more pagination/extraction is required.

Sources:
- https://khadlaj-perfumes.com/collections/khadlaj-new-launches?page=2
- https://frenchavenue.com/collections/all

### Latest integrity snapshot
- 1,260 canonical identities
- 141 explicit variant rows
- 31 discovery families
- Bujairami: 121 identities
- Khadlaj: 48 identities
- French Avenue: 30 identities
- 0 duplicate product IDs; 0 duplicate variant IDs; 0 orphan variants; 0 canonical products missing from discovery registry


## Further pagination — French Avenue and Khadlaj — 2026-11-08

### French Avenue
Inspected page 3 of the official French Avenue all-products collection and added 12 missing fragrance identities: Prune Hypnos, Spirito Mystic, Ravine Ginger, Nuit, Irida, Sagittarius, Soir, Sweet Paradise, Zenith Tobacco, Tropical Kiss, Signature White and Miraj Absolu. Current French Avenue catalog count: **42**. The official collection reports 142 total products and has a load-more/pagination path; this remains a partial import.

The same page lists **Aromatix Plantine Blanc**. The catalog already contained Aromatix **Platine Blanc**; I added the source spelling as an alias on that existing Aromatix identity rather than creating a duplicate perfume. Source: https://frenchavenue.com/collections/all?page=3 .

### Khadlaj
Inspected page 3 of Khadlaj's official 89-item new-launch collection and added four missing perfumes: Zayaan Gold, Biscotti Caramel Pop, Oud Pour Leather and Private Blend (the product detail confirms the fuller descriptor “Private Blend Tobac Extra”). Current Khadlaj catalog count: **52**. La Fede-branded items shown in the same collection were not re-attributed to Khadlaj; the parent/sub-brand boundary must remain clear. Source: https://khadlaj-perfumes.com/collections/khadlaj-new-launches?page=3 and https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/private-blend-tobac-extra-extrait-de-parfum-100-ml-for-men .

### Latest integrity snapshot
- 1,276 canonical identities
- 141 explicit variant rows
- 31 discovery families
- Bujairami: 121 identities
- Khadlaj: 52 identities
- French Avenue: 42 identities
- 0 duplicate product IDs; 0 duplicate variant IDs; 0 orphan variants; 0 canonical products missing from discovery registry


## Afnan, Lattafa and Al Haramain official-source increment — 2026-11-08

### Afnan
The official global all-products collection reports 120 items. The first rendered page was inspected; after excluding deodorants, gift sets, travel sets and discovery kits, 11 missing fragrance identities were added: ABIYAD MUKHALLAT, ABIYAD MUSK, ABIYAD SANDAL, ADWAA AL SHARQ, DEHN AL OUDH ABIYAD, Delicious Bouquet, Ebdaa Concentrated Perfume Oil, EDICT AMBERYTHME, EDICT MUSCTIQUE, EDICT OUDDICTION and FAKHAR AL JAMAAL. Cherry Bouquet and Historic Doria were already present. Current Afnan catalog count: **58**. This is not a full extraction of 120 items; further pages and product classification remain.
Source: https://afnan.com/collections/all .

### Lattafa
The official Lattafa Perfumes category showed Raed Absolu, Raed Intensely and Liam Blue Shine, all missing from the catalog. Added all three. Current Lattafa count: **19**.
Source: https://lattafa.com/product-category/lattafa-perfumes/ .

### Al Haramain
The official EU shop's all-products collection reports a multi-page catalogue (198 items). Added 25 missing fragrance / concentrated perfume oil identities visible in its listing: Junoon Oud, Detour Noir, Platinum Oud, Rose Oud, Wardi, Rawaa, Detour Rouge, Signature Blue, Portfolio Imperial Oud, Portfolio Royale Stallion, Oyuny, Opulent Sapphire, Manege Rouge, Portfolio Floral Sculpture, Portfolio Euphoric Roots, Musk Al Haramain Noir, Amber Musk, Mystique Musk Spray, Treasure, L'Aventure Gold, Royal Musk, Xplore Sapphire, Tanasuk, Almas Gold, Almas Silver, Dehnal Oudh Ateeq and Salam Attar. The actual added count is 25; product listing rows that represent multiple sizes of an existing fragrance were not duplicated as separate identities. Travel packs and gift sets were excluded. Current Al Haramain count: **61**. The 198-item shop count includes multiple variants and non-perfume formats, so it is not a count of 198 distinct fragrance identities.
Source: https://shop.alharamainperfumes.com/eu/collection.html .

### Latest integrity snapshot
- 1,315 canonical identities
- 141 explicit variant rows
- 31 discovery families
- Afnan: 58 identities; Lattafa: 19; Al Haramain: 61
- 0 duplicate product IDs; 0 duplicate variant IDs; 0 orphan variant rows; 0 canonical products missing from discovery registry

The requested-brand source audit remains incomplete; these are incremental additions only.


## Incremento successivo — Lattafa e Afnan (2026-11-08)

Aggiunte **28 nuove identità canoniche** dopo confronto con ulteriori pagine ufficiali:

- **Lattafa: +11** — Berry On Top, Washwasha, Musk Salama, Eclaire Pistache, Eclaire Banoffi, Ana Abiyedh Scarlet, Dynasty, Ana Abiyedh Leather, Fire On Ice, Habik Women, Habik Men. Fonte ufficiale: https://lattafa.com/product-category/lattafa-perfumes/page/3/ .
- **Afnan: +17** — Historic Sahara, Kiaana Angel, LA FLEUR BOUQUET, LILIA, Malak, MODEST DEUX, ORNAMENT POUR FEMME, ORNAMENT POUR HOMME, OUD RISING, PARIS OUD, PATCHOULI ON FIRE, PORTRAIT REVIVAL, RARE PASSION, Stardust, SUPREMACY IN OUD - LUXURY COLLECTION, SUPREMACY INCENSE, SUPREMACY NOIR. Fonte ufficiale: https://afnan.com/collections/all?page=2 .

Sono stati esclusi deodoranti, discovery kit, set e confezioni multiple. Non sono stati dedotti formati, concentrazioni, GTIN, prezzi o disponibilità. Gli elementi già presenti non sono stati duplicati.

### Integrity snapshot aggiornato
- **1.343** identità canoniche nel catalogo.
- **141** righe variante.
- **31** famiglie nel family registry.
- Lattafa: **30** identità; Afnan: **75**; Al Haramain: **61**.
- **0** product ID duplicati; **0** variant ID duplicati; **0** varianti orfane; **0** prodotti canonici senza famiglia corrispondente nel registry.

La copertura dei marchi resta parziale: le pagine e le categorie ufficiali non sono ancora state tutte estratte e classificate. Il conteggio non è una dichiarazione di completezza.

## Ulteriore incremento — Lattafa pagine 11/13 e Afnan pagina 3 (2026-11-08)

Aggiunte **31 nuove identità canoniche**:

- **Lattafa: +23** — Mohra, Khamrah, Suqaraat, Al Noble Safeer, Al Noble Wazeer, Al Noble Ameer, Confidential Private Gold, Raghba, Velvet Rose, Qaed Al Fursan Unlimited, Hayaati Florence, Badee AL Oud Sublime, Maahir Black Edition, Maahir, Opulent Musk, Qaaed, Raed Luxe, Qimmah For Women, Qaed Al Fursan, Ramz Lattafa Gold, Ramz Lattafa Silver, Velvet Oud e Oud Mood. Fonti ufficiali: https://lattafa.com/product-category/lattafa-perfumes/page/11/ e https://lattafa.com/product-category/lattafa-perfumes/page/13/ .
- **Afnan: +8** — SUPREMACY NOT ONLY INTENSE - LUXURY COLLECTION, SUPREMACY TAPIS ROUGE - LUXURY COLLECTION, TASNEEM, TOBACCO RUSH, TURATHI RED, VIOLET BOUQUET, WARD AL USSHAQ e ZABARJAD. Fonte ufficiale: https://afnan.com/collections/all?page=3 .

Le varianti di volume, i deodoranti e i set non sono stati trasformati in identità separate. Le identità già registrate sono state mantenute senza duplicazione.

### Integrity snapshot aggiornato
- **1374** identità canoniche.
- **141** righe variante.
- **31** famiglie nel registry.
- Lattafa: **53**; Afnan: **83**.
- **0** product ID duplicati; **0** variant ID duplicati; **0** varianti orfane; **0** prodotti senza famiglia corrispondente nel registry.

La copertura completa dei marchi resta da verificare; il numero attuale rappresenta solo le identità individuate e trascritte dalle pagine citate.

## Incremento Lattafa — pagine ufficiali 6 e 7 (2026-11-08)

Aggiunte **23 identità** ulteriori al catalogo Lattafa:
Al Nashama Caprice, Kingdom Men, Kingdom Women, Angham, Ajwad Pink to Pink, Sehr Lattafa, Qaaed Al Shabaab, Mahasin Crystal, Emeer, Ameer Al Arab Imperium, Ameer Al Oud, Adeeb, Maitha, Mohra Silky Rose, Abraaj, Haakim, Amoura, Raneen, Victoria, Lail Maleki Moroccan Blue, Mashrabya, Mayar Cherry Intense e Afeef.

Fonti ufficiali:
- https://lattafa.com/product-category/lattafa-perfumes/page/6/
- https://lattafa.com/product-category/lattafa/page/7/

Sono state importate solo identità di profumi e oli profumati nominati nel catalogo. Deodoranti, spray corpo, gift set e kit non sono stati aggiunti come profumi. Non sono stati inventati formati, prezzi o disponibilità.

### Integrity snapshot
- **1397** identità canoniche.
- **141** righe variante; **31** famiglie.
- Lattafa: **76**; Afnan: **83**.
- Product ID duplicati: **0**; variant ID duplicati: **0**; varianti orfane: **0**; prodotti senza famiglia registry: **0**.

La copertura del marchio non è ancora completa: sono state esaminate solo alcune pagine selezionate del catalogo ufficiale.


## Incremento successivo — Lattafa pagine 2/3 e Afnan Europe pagina 2 (2026-11-08)

Aggiunte **17 identità canoniche** dalle pagine ufficiali:

- **Lattafa: +13** — Pure Crystal, Nasmaat, Layaan, Sherif, Choco Overdose, Mallow Madness, Cookie Crave, Whipped Pleasure, Vanilla Freak, Taureau De Combat, Nebras Elixir, Nadira e Safeer. Fonti: https://lattafa.com/product-category/perfumes/page/2/ e https://lattafa.com/product-category/perfumes/page/3/ . Le due ultime identità sono state attribuite alla pagina 3.
- **Afnan: +4** — Highness IV, Highness V, Highness IX e Highness X. Fonte: https://www.afnaneurope.com/collections/all-products?page=2 .

Set, gift set e travel kit sono stati esclusi. Non sono stati inventati dati su formati, prezzi, disponibilità o codici prodotto.

### Integrity snapshot aggiornato
- **1414** identità canoniche.
- **141** righe variante.
- **31** famiglie nel registry.
- Lattafa: **89**; Afnan: **87**.
- Product ID duplicati: **0**; variant ID duplicati: **0**; varianti orfane: **0**; prodotti senza famiglia corrispondente: **0**.

Il catalogo dei marchi resta parziale: il conteggio descrive le identità attualmente censite, non una copertura totale garantita.
