# Catalog brand coverage audit — 2026-11-07

## Scope

Requested fragrance houses and lines:
- Velixir
- Mykonos
- Maison Asrar
- Khadlaj
- Bujairami
- Paris Corner
- Assaf
- Al Wataniah
- Armaf
- French Avenue
- Arabiyat Prestige
- Gulf Orchid
- Swiss Arabian
- Games of Spades
- Lattafa
- Afnan
- Aromatix
- Maison Alhambra
- Zimaya
- Al Haramain

Branch reviewed: `catalog/complete-brand-expansion-2026-11`
Current catalog snapshot (revalidated on branch head): **1,589 canonical product identity records; 149 variant records; 21 brand labels**. This replaces the earlier 1,153-record snapshot below.

## Current counts (catalog records, not proof of completeness)

The counts below are the exact current JSON snapshot on this branch, not a claim that each brand's complete official range has been reconciled.

| Brand / line | Records |
|---|---:|
| Velixir | 28 |
| Mykonos | 72 |
| Maison Asrar | 121 |
| Khadlaj | 113 |
| Bujairami | 40 |
| Paris Corner | 129 |
| Assaf | 115 |
| Al Wataniah | 22 |
| Armaf | 247 |
| French Avenue | 26 |
| Arabiyat Prestige | 32 |
| Gulf Orchid | 19 |
| Swiss Arabian | 53 |
| Games of Spades | 4 |
| Lattafa | 138 |
| Afnan | 71 |
| Aromatix | 12 |
| Maison Alhambra | 237 |
| Zimaya | 71 |
| Al Haramain | 37 |
| Giorgio Armani (pre-existing records) | 2 |
| **Total** | **1,589** |

## Findings from live public sources

### Paris Corner
- Official all-products collection page currently exposes **255 products**.
- It also explicitly groups distinct labels/collections: Paris Corner, Ministry of Oud, North Stag, Pendora, Emir and Magic Oud Series.
- The ScentHunter catalog currently has 33 records under the exact brand label `Paris Corner`.
- Gap: a substantial reconciliation is still required. The 255 collection count must be filtered for fragrance products, gift sets, and non-perfume products before import. The product listing is paginated, so the visible first page is not the full product inventory.
- Official source: https://www.pariscornerperfumes.com/collections/all

### Khadlaj
- Official collections page says **308 products** in “All Products”, but the same page separates air fresheners, bakhoor, perfume oils, gift sets, home fragrance and perfume sprays.
- It lists **88 products** in the Khadlaj perfume-spray collection and additional EDP/extrait/collection categories.
- ScentHunter currently has 41 exact-brand records.
- Gap: inventory must be reconciled by fragrance SKU and format, excluding room/air products and de-duplicating repeated collection memberships.
- Official source: https://khadlaj-perfumes.com/collections

### Maison Asrar
- Official site separates “Fragrances”, “Room Spray” and “Home Fragrances”; only the fragrance section should feed the perfume catalog.
- An independent specialist index lists 116 Maison Asrar scents and explicitly says it is not the official brand site. It is useful as a cross-check, not a primary authority.
- ScentHunter currently has 121 exact-brand records, so the difference is not evidence of better coverage: at least five names need reconciliation against official fragrance product pages and possible spelling/alias/duplicate issues.
- Official source: https://maisonasrar.com/
- Independent cross-check: https://maisonasrarperfumes.eu/perfumes/

## Data quality warnings

- Catalog records marked `source_listed_name` are candidate identities, not independently verified commercial SKUs.
- A brand collection URL is not a product-level source URL. It does not prove the specific product, size, concentration, GTIN, or availability.
- Do not create variant rows from assumed sizes. Populate GTIN, size, concentration and product URL only from product-level evidence.
- Product identity records must not be confused with retailer offers or live prices.

## Required next actions

1. Crawl/paginate each brand's official fragrance collection where public and permitted.
2. Save raw page/JSON snapshots as dated fixtures, with retrieval timestamp and source URL.
3. Extract product-level title, product URL, SKU/GTIN, concentration and size only when actually present.
4. Normalize and compare against the current catalog by brand + name + concentration + size; use GTIN for exact identity when present.
5. Produce per-brand missing / matched / ambiguous / non-perfume reports.
6. Add only source-supported missing perfume identities; put ambiguous names into a review queue.
7. Keep this PR draft until reconciliation tests pass.

## Current conclusion

Historical note: this conclusion referred to the earlier 1,153-record snapshot and is superseded by the current 1,503-record count above. The catalog is still **not defensible to call complete**. Paris Corner and Khadlaj need further reconciliation; Maison Asrar's current 121 records must be checked against official fragrance-only listings, not compared as a raw total to a secondary index.


## Additional product-level listing reconciliation — 2026-11-07 evening

Cross-checked current catalog identities against visible product listings in a European specialist retailer/distributor collection. Added only exact names visibly listed and absent from ScentHunter; no duplicate brand + name pair was added.

New identities added in this pass: 34.
- Khadlaj: Karus Secret Musk; Rose And Romance; Hareem Al Sultan Blue.
- French Avenue: Jade Giallo; Grecia Rosa; Vulcan Baie; Vulcan Sable; Grecia; Diwani Rabat; Diwani Cairo.
- Gulf Orchid: Tahiti Colada; Cookie Bite; Marshmallow; Baklava Bite; Sweet Like Candy; Naughty Vanilla; Banana Split; Pink Marshmallow; Heavenly Lychee.
- Bujairami: Next Level; Sovereign; Candy Crush; High Roller; Madness Extreme; Unforgettable; Vanilla Dreams.
- Assaf: Miss Sakura; Frankel Black Elixir; Copacabana.
- Arabiyat Prestige: Sugarcane Vanilla; Noirè Absolu; Noire; Swar Venin; Gelato Black Currant Lolly.

Source collection pages:
- Khadlaj: https://www.orientfragance.com/en/collections/khadlaj-perfumes
- French Avenue: https://www.orientfragance.com/en/collections/french-avenue
- Gulf Orchid: https://www.orientfragance.com/en/collections/perfumes-gulf-orchid
- Bujairami: https://www.orientfragance.com/en/collections/bujairami
- Assaf: https://www.orientfragance.com/en/collections/assaf
- Arabiyat Prestige: https://www.orientfragance.com/en/collections/arabiyat-prestige-distribuidor-oficial-perfumes-arabes

Important: these are product-listing observations from a retailer/distributor, not official brand master catalogs. Collection pagination, availability and product ranges can vary by country and date. These names are source-listed identity candidates only. No unverified sizes, concentrations, GTINs or retailer offers were inferred.

## Updated totals

- Canonical product identities: 1187
- Variant records retained: 141
- Duplicate product IDs: 0
- Duplicate brand + canonical-name pairs: 0

### Updated counts by requested brand

- Velixir: 28
- Mykonos: 72
- Maison Asrar: 121
- Khadlaj: 44
- Bujairami: 40
- Paris Corner: 33
- Assaf: 115
- Al Wataniah: 22
- Armaf: 190
- French Avenue: 26
- Arabiyat Prestige: 32
- Gulf Orchid: 19
- Swiss Arabian: 42
- Games of Spades: 4
- Lattafa: 19
- Afnan: 55
- Aromatix: 12
- Maison Alhambra: 203
- Zimaya: 71
- Al Haramain: 37


## Priority-brand reconciliation pass 2 — 2026-11-07

### Official-source checks

- Lattafa official perfume category: https://lattafa.com/product-category/perfumes/ . The visible page includes perfume identities such as Fahad, Khamrah Waha, Sheikh Al Shuyukh Supreme, Jouri, Ana Abiyedh Passion, Ameerat Al Arab Sugar Crown, Angham Second Song, Maahir Honor, Dalal, Yara Elixir and Asad Elixir. All ten checked names were already present in the current Lattafa catalog, so no duplicates were added from this sample. This is a page-level spot check, not a full collection reconciliation.
- Afnan official site: https://afnan.com/ . Its navigation distinguishes Eau de Parfum, Extrait, concentrated perfume oil and gift sets; the homepage's visible top products were compared with the current list. No new identity was added from the limited visible sample. A complete paginated product-list export is still required.
- Armaf official all-fragrances collection: https://armaf.com/collections/all-perfumes . It reports 464 products, but its filters show mixed formats including 248 Eau de Parfum plus body mist, body spray, deodorant, lotion, roll-on, shampoo, shower gel and other formats. Do not use 464 as a perfume-only count. Visible perfume names checked were already represented in the catalog; full pagination and format filtering remain open.
- Paris Corner official all-products collection: https://www.pariscornerperfumes.com/collections/all . It currently reports 252 products and includes multiple labels (Paris Corner, Ministry of Oud, North Stag, Pendora, Emir and Magic Oud Series). The visible first-page sample overlaps heavily with current records. Do not assign every sub-label product to the Paris Corner brand. Full product-level pagination and correct sub-brand attribution remain open.
- Swiss Arabian Oman official shop: https://om.swissarabian.com/products/ and https://om.swissarabian.com/collections/ . Added 11 additional exact fragrance names visible in the official shop collection and absent from the catalog: Oud Malaki, Edge Intense, Secret Musk, Kashkha, Rasheeqa, Dehn El Oud Cambodi, Oud And Lychee, Rose And Patchouli, Shaghaf Oud Elixir, Oud 74, Secret Rose. The same shop also lists non-fragrance and home/incense formats; those were not imported as perfume identities.
- Maison Alhambra: no reliable official master catalog was established in this pass; no additions made. Need brand-authorized or primary-source product pages before asserting completeness.

### Pass 2 outcome

- New identities added in this pass: 11 (all Swiss Arabian).
- Lattafa: 10 visible official perfume names sampled; all already in the catalog.
- Afnan: limited homepage sample; no additions.
- Armaf: official collection sample checked; 464 count includes non-EDP formats and non-perfume formats; full reconciliation pending.
- Paris Corner: official all-products collection reports 252 items across several labels; sub-brand attribution and perfume-only filtering pending.
- Maison Alhambra: primary-source catalog still missing; no speculative additions.


## Updated catalog totals after pass 2

- Product identities: 1198
- Variants: 141
- Duplicate IDs: 0
- Duplicate brand + canonical-name pairs: 0


## Priority-brand reconciliation pass 3 — official UK/primary listing spot-check

### Paris Corner

The official all-products collection currently renders 255 products (the earlier 252 figure was stale). It visibly identifies distinct labels/collections including Paris Corner, Ministry of Oud, North Stag, Pendora and Emir; do not attribute every item to the core Paris Corner label without line-level evidence. From the visible first page, added nine exact product names absent from the existing Paris Corner list: Atomise Intensive Men, Attractus, Camaro Homme Intense, Charuto Mysterious Tobacco, Cherry Gossip, Choco Cult, Cornflower Delight, Cosmopolitan Dubai and Cosmopolitan London. Source: https://www.pariscornerperfumes.com/collections/all . Existing names on the same page were not duplicated. This is a first-page spot-check only; remaining pages and product-line ownership still need reconciliation.

### Armaf

The official ARMAF UK collection currently reports 313 products and has separate categories for Eaux de Parfum, Eaux de Toilette, perfume extracts, perfumes/colognes, body mists, deodorants, bath/body, gift sets and samples. Added three exact fragrance names absent from the current Armaf list from its visible product listing: Club De Nuit Overdose John Abraham Edition, Connoisseur Man and Odyssey Homme Mandarin Sky Limited Edition. Source: https://armaf.uk/collections/all-armaf-products . Did not add body sprays, gift sets, samples or duplicate sizes as separate canonical fragrance identities. The US official all-fragrances page separately reports 464 products and lists 248 EDPs plus other concentrations and body-care formats; it is not a clean count of unique perfume identities.

### Pass 3 outcome

- New identities added: 12 (9 Paris Corner, 3 Armaf).
- Paris Corner: 42 identities in this catalog after the additions; official 255-item collection includes multiple product labels and remains only partially reconciled.
- Armaf: 193 identities in this catalog after the additions; official UK 313-item listing has mixed formats and eight pages, so full reconciliation remains pending.
- No claims of brand completeness are made.


## Catalog totals after pass 3

- Product identities: 1210
- Variants: 141
- Duplicate product IDs: 0
- Duplicate brand + canonical-name pairs: 0


## Priority-brand reconciliation pass 4 — Paris Corner pages 2–3 and Armaf pages 3–4

### Paris Corner official core-brand collection

The official `/collections/paris-corner` collection reports 105 products and has separate pages. Page 2 lists names from Jardin Des Papillons through Oravea; page 3 lists Oud Faek through Twilight Shadow Musk Collection. Added 32 exact names absent from the catalog from page 2 and 32 exact names absent from the catalog from page 3. Sources:
- https://www.pariscornerperfumes.com/collections/paris-corner?page=2
- https://www.pariscornerperfumes.com/collections/paris-corner?page=3

The collection count can include different presentations/collections, so this is not yet a unique canonical fragrance count. We are preserving exact official listing names pending product-page review. Some titles containing "Collection" may be a family or set rather than an individual fragrance; these are flagged for a later product-page type check and should not be considered validated standalone perfumes until confirmed.

### Armaf official UK collection

Continued reviewing official collection pages 3 and 4. Added six exact fragrance names absent from the catalog: Odyssey Lichi Lush, Lion's Club Courageux, Infinity Gold, Private Key To My Soul, Lion's Club Monarque, Odyssey Femme White Edition. Source: https://armaf.uk/collections/all-armaf-products?page=4 . Page 3 had been reviewed in the previous pass; page 4 includes non-fragrance formats such as shower gel, discovery sets and deodorant, which were not added as canonical perfumes. Two titles (Miss Chic and Miss Mistique) were deliberately held back because they appear closely related to existing Miss Armaf identities and need product-page/GTIN disambiguation before creating new canonical records.

### Pass 4 outcome

- Added 38 identities: 32 Paris Corner and 6 Armaf.
- Paris Corner core collection has 105 listed products; pages 2–3 now reconciled at the visible-name level, but page 1 and product type/brand hierarchy still need a complete exact comparison.
- Armaf official UK collection has 7 pages; pages 1–4 have now been reviewed at listing level, but pages 5–7 and mixed formats remain open.
- No brand completeness claim is made.


## Updated catalog totals after pass 4

- Product identities: 1287
- Variants: 141
- Duplicate IDs: 0
- Duplicate brand + canonical-name pairs: 0


## Priority-brand reconciliation pass 5 — Armaf UK pages 5–7 and Maison Alhambra distributor pages 1–4

### Armaf UK

Reviewed official ARMAF UK collection pages 5, 6 and 7. The pages explicitly separate EDP/EDT/extrait fragrances from body mist, deodorant, gift sets, perfume oils and discovery sets. Added 33 exact names from these pages that were not present as exact Armaf canonical names in the catalog: Space Age; Sacre Bleu; Miss Voce Vive; Miss Magnifiq; Miss Dazzling; Magical Oud For Eter; Le Femme; La Rosa; Tres Nuit Lyric Pour Homme; Miss Grandeur; Profumi D'Art 14 Latte Di Tuberosa; Profumi D'Art 06 Vaniglia Esotica; Twist Debois; Sapphire Niche; Profumi D'Art 13 E Tanta Roba; Profumi D'Art 01 Acqua Mia; Perfume Oasis For Eter; Lion's Club Rugir; Lionheart Heritage For Women; Legasi For Women; Le Parfait Azure; Fade Denim Edit; Evening Rose; Eternia Italia; Eternia Imperia; Cloisonne; Blooming Maguey; Affecte; Ego Panthera; Desert Rose For Eter; Desert Flower For Eter; Craze For Men; Bucephalus X.

Sources: https://armaf.uk/collections/all-armaf-products?page=5 ; https://armaf.uk/collections/all-armaf-products?page=6 ; https://armaf.uk/collections/all-armaf-products?page=7 . Exact naming is preserved from retailer listing. Potential naming aliases (for example, reversed line/name order) should be reconciled before final product publication. Existing variants/sizes were not duplicated as separate identities.

### Maison Alhambra

Used the European B2B distributor's Maison Alhambra brand catalogue, which explicitly separates LATTAFA MAISON ALHAMBRA from Lattafa air fresheners, deodorants and other sub-brands. Pages 1–4 list 100ml/80ml EDP identities and SKUs; added 34 absent identities in total across these pages: 10 from page 1 and 24 from pages 2–4 (9 + 6 + 9). Names added:

- Page 1: Sensual Vanilla; Your Touch Amber; Yeah! Man; Your Touch for Women; Jean Lowe Maitre; Winsome; Queenstown Pour Femme Intense; Spectrum; Victoria Flower Rosa Lilium; Victorioso Heroic. (Florenza was already in catalog.)
- Page 2: Tonic Malt; Tonic Ice; Encode Mountain; Vogue Party; Vogue Rouge; Vogue Night; Pink Velvet; Smoky Touch; Sceptre Oceana.
- Page 3: Victorioso Legacy; Camille; Rose Origami; Jorge Di Profumo Deep Blue; Vanilla Blush; Coeur Sunny.
- Page 4: Kismet for Men; Winsome L'Exclusif; Oasis; Philos Opus Noir; Bronze; Luminous Gris; Sugar Me Carrot Cake; Summit Elixir; Dominate Absolu.

Sources: https://b2b.perfumecenter.eu/brand.aspx?id=4 and pages `?page=2`, `?page=3`, `?page=4`. The source is a specialist European B2B distributor, not the manufacturer's master database; treat as distributor-listed evidence. The catalogue explicitly identifies EDP and volume, but the catalog additions preserve the name and EDP concentration without inventing GTINs or stock.

### Pass 5 outcome

- Armaf: 33 new names from official UK pages 5–7.
- Maison Alhambra: 34 distributor-listed names across pages 1–4; ten page-one additions plus 24 additions on pages 2–4. (One page-one name, Florenza, already existed and was not duplicated.)
- Armaf pages 1–7 have now been checked at listing level; pages may paginate differently over time and the collection still contains non-perfume categories.
- Maison Alhambra distributor pages 1–4 have been checked; the distributor shows 4 pages, but this is not proof of the entire global Maison Alhambra catalogue.
- No brand completeness claim is made.


## Updated catalog totals after pass 5

- Product identities: 1354
- Variants: 141
- Duplicate product IDs: 0
- Duplicate brand + canonical-name pairs: 0


## Priority-brand reconciliation pass 6 — Paris Corner first-page gap and Afnan Europe catalogue

### Paris Corner

Reopened the official core-brand collection: it currently reports 105 products, with the product list visible across the collection's paginated pages. The first-page listing includes a group of names absent from the existing catalog; added 14 exact names: Eshal Musk, Eshal Vanilla, Eternal Coffee, Eternal Meadows, Eternal Musk, Farah, Fatal Embrace, Fayora, Fayora Oshino, Green Bet, Heer, Hurriya, Ibisco Nirvana and Indomitable. Source: https://www.pariscornerperfumes.com/collections/paris-corner .

Important reconciliation issue: the ScentHunter Paris Corner bucket now contains 120 names, which is higher than the live official collection's 105-item count. This is not automatically an error because prior pages and retailer listings may include discontinued products or names listed in different product-line groupings, but it means the Paris Corner bucket cannot be called reconciled or complete. Next pass must compare all 105 current official product names one by one, identify stale/discontinued entries and distinguish product-line ownership. The 105 count is current as observed; it may change.

### Afnan Europe

Used the official European Afnan shop, whose all-products page currently shows 64 products. It separates EDP, Extrait and concentrated perfume oil, and separately exposes home fragrances and gift sets. Added 11 absent perfume identities visible in the catalogue: Stardust, Historic Sahara, Tobacco Rush, Portrait Revival, Ornament Pour Homme, Kiaana Angel, Edict Amberhythm, Edict Ouddiction, Supremacy Tapis Rouge, Oud Rising and Fakhar Al Jamaal. Source: https://www.it.afnan.com/collections/all-products .

The 64-item total is not a unique perfume-only count: the page includes gift sets and discovery sets. The current ScentHunter Afnan bucket is still only a partial match to the official product assortment. The oil-format products are not automatically merged into EDP identities; a future schema field should preserve concentration/type explicitly.

### Lattafa check

The official Lattafa perfume category shows three pages. The visible first-page names (Fahad, Khamrah Waha, Sheikh Al Shuyukh Supreme, Jouri, Ana Abiyedh Passion, Ameerat Al Arab Sugar Crown, Lattafa Mishlah, Angham Second Song, Maahir Honor, Dalal, Yara Elixir, Asad Elixir) are already present in the ScentHunter Lattafa bucket. No additions were made from this first-page sample. Source: https://lattafa.com/product-category/perfumes/ . A full second- and third-page reconciliation is still required.

### Pass 6 outcome

- Added 25 names: 14 Paris Corner, 11 Afnan.
- Paris Corner official current collection count: 105; catalog bucket: 120; exact one-to-one reconciliation remains open.
- Afnan official Europe all-products count: 64 mixed items; catalog bucket after additions: 66; full fragrance-only reconciliation remains open.
- Lattafa first-page spot-check: 12/12 visible names already represented; pages 2–3 pending.
- No brand completeness claim is made.


## Updated catalog totals after pass 6

- Product identities: 1379
- Variants: 141
- Duplicate product IDs: 0
- Duplicate brand + canonical-name pairs: 0


## Priority-brand reconciliation pass 7 — Afnan concentration categories and quality cross-check

### Afnan official Europe category reconciliation

Inspected the official European Afnan category pages separately, rather than treating the 64-item all-products collection as 64 fragrances:
- Eau de Parfum collection: https://www.it.afnan.com/collections/eau-de-parfum (42 listed items, including some collection kits/sets that must be excluded from standalone perfume identities).
- Extrait de Parfum collection: https://www.it.afnan.com/collections/extrait-de-parfum (15 listed items).
- Concentrated perfume oil: https://www.it.afnan.com/collections/concentrated-perfume-oil (1 listed item, Abiyad Musk).

Added five absent names from the official Extrait collection, with the type recorded as `Extrait de Parfum`: Patchouli On Fire, Highness IV, Highness V, Highness IX and Highness X. These were not in the previous Afnan list. The existing Afnan list already included the other visible Extrait names checked, including 9 PM Night Out, 9 PM Elixir, Rare Reef, Supremacy Not Only Intense, Historic Sahara, Tobacco Rush, Edict Amberhythm, Supremacy Tapis Rouge, Edict Ouddiction and Oud Rising.

Important: the Afnan official European all-products page and type pages have different counts due to collection membership, duplicate featured products, gift sets and category filters. Do not sum the counts as unique fragrances. Oil-format products should have their own format/concentration field in the catalog schema instead of being conflated with EDP/Extrait. The current catalog's Afnan bucket is 71 identities, but it is not yet a final global range count.

### Paris Corner first-page audit reminder

The official Paris Corner core-brand collection currently reports 105 products. The current ScentHunter Paris Corner bucket is 120. The first-page gap additions have been recorded, but this count mismatch remains unresolved. We need to compare exact official product handles and product pages, identify discontinued/duplicate items, and preserve sub-brand attribution. No additional Paris Corner names were added in this pass.

### Pass 7 outcome

- Added 5 Afnan Extrait identities from the official European shop.
- Afnan bucket now: 71.
- Paris Corner bucket remains: 120 versus 105 currently listed on the official core-brand collection; exact reconciliation remains open.
- No brand completeness claim is made.


## Updated catalog totals after pass 7

- Product identities: 1384
- Variants: 141
- Duplicate product IDs: 0
- Duplicate brand + canonical-name pairs: 0


## Priority-brand reconciliation pass 8 — Lattafa official perfume archive pages 3 and 11

The official Lattafa site exposes a dedicated `Lattafa Perfumes` archive with 13 pages. The category is distinct from deodorants, perfume mists, air fresheners, personal care and gift sets. Reviewed official archive pages 3 and 11 and added 23 exact perfume names absent from the current Lattafa catalog.

Page 3 additions (11): Berry On Top; Washwasha; Musk Salama; Eclaire Pistache; Eclaire Banoffi; Ana Abiyedh Scarlet; Dynasty; Ana Abiyedh Leather; Fire On Ice; Habik Women; Habik Men. Source: https://lattafa.com/product-category/lattafa-perfumes/page/3/ . The Yara 5ml Collection was deliberately excluded as a discovery/mini set.

Page 11 additions (12): Mohra; Khamrah; Suqaraat; Al Noble Safeer; Al Noble Wazeer; Al Noble Ameer; Confidential Private Gold; Raghba; Velvet Rose; Qaed Al Fursan Unlimited; Hayaati Florence; Badee Al Oud Sublime. Source: https://lattafa.com/product-category/lattafa-perfumes/page/11/ .

The archive shows 13 pages, so checking only pages 1, 3 and 11 does not complete Lattafa. Other brand-specific categories (Lattafa Pride, Niche Emarati) must be kept distinct from the main Lattafa perfume label unless a clear brand taxonomy is established. Exclude deo, mist, air freshener and gift-set SKUs from the canonical perfume identity list.

### Pass 8 outcome

- Added 23 Lattafa perfume identities from official archive pages 3 and 11.
- Lattafa bucket now: 42.
- Pages still unreviewed: 2 and 4–10, 12–13.
- No brand completeness claim is made.


## Updated catalog totals after pass 8

- Product identities: 1407
- Variants: 141
- Duplicate product IDs: 0
- Duplicate brand + canonical-name pairs: 0


## Priority-brand reconciliation pass 9 — Lattafa official archive pages 2, 4–8, 10, 12–13

Reviewed the official Lattafa Perfumes archive pages that had remained unchecked, excluding page 9 which did not return reliably during this pass. Compared each listed name against the existing Lattafa identities and added 96 new names from the official archive. Names are preserved as listing-level identities; no size, GTIN, SKU, stock, price or concentration was inferred. Gift sets and multi-product collections were excluded.

### Additions by official archive page

- Page 2 (8): Nasmaat; Layaan; Sherif; Choco Overdose; Mallow Madness; Cookie Crave; Whipped Pleasure; Vanilla Freak.
- Page 4 (10): Asad Zanzibar Limited Edition; Fakhar Lattafa Platin; Petra; Opulent Dubai; Qaed Al Fursan Untamed; Atheeri; Khamrah Dukhan; Ana Abiyedh Coral; Mohra Silky Rose; Victoria. My Yara Collection and Anniversary Edition were excluded as sets.
- Page 5 (11): Lail Maleki Moroccan Blue; Mashrabya; Mayar Cherry Intense; Afeef; Teriaq Intense; Badee Al Oud Noble Blush; Her Confession; His Confession; Badee Al Oud Amethyst; Atlas; Yara Candy.
- Page 6 (12): Al Nashama Caprice; Kingdom Men; Kingdom Women; Angham; Ajwad Pink to Pink; Sehr Lattafa; Qaaed Al Shabaab; Mahasin Crystal; Emeer; Ameer Al Arab Imperium; Ameer Al Oudh; Adeeb.
- Page 7 (11): Oud Najdia; Musk Sugar Plum; Musk Candy Rose; Fakhar Lattafa Women; Hayatim; Pure Musk; Raed Silver; Safwaan Lauture Oud; Mayar; Yara Tous; Rouat Al Oud.
- Page 8 (12): Qimmah For Men; Oud Mood Reminiscence; Oud Mood Elixir; Musk Mood; Oud Lail Maleki; Fakhar Lattafa Men; Awraq Al Oud; Musk So Poudree; Musk Wild Vanille; Raed Oud; Eclaire; Ameerat Al Arab.
- Page 10 (11): Qaed Al Fursan; Sheikh Al Shuyukh Luxe Edition; Ramz Lattafa Gold; Ramz Lattafa Silver; Velvet Oud; Oud Mood; Ejaazi; Lail Maleki; Najdia; Badee Al Oud Oud For Glory; Musamam.
- Page 12 (12): Yara Moi; Sakeena; Emaan; Hayaati Al Maleky; Ajayeb Dubai Portrait; Jasoor; Mayar Natural Intense; Khamrah Qahwa; Aura; Ta’weel; Teriaq; Musamam White Intense.
- Page 13 (9): Ajayeb Dubai; Ana Abiyedh Rouge; Hayaati Gold Elixir; Hayaati; Fakhar Lattafa Extrait; Ameer Al Oudh Intense; Al Dur Al Maknoon Silver; 24 Carat White Gold; 24 Carat Pure Gold.

Official sources:
- https://lattafa.com/product-category/lattafa-perfumes/page/2/
- https://lattafa.com/product-category/lattafa-perfumes/page/4/
- https://lattafa.com/product-category/lattafa-perfumes/page/5/
- https://lattafa.com/product-category/lattafa-perfumes/page/6/
- https://lattafa.com/product-category/lattafa-perfumes/page/7/
- https://lattafa.com/product-category/lattafa-perfumes/page/8/
- https://lattafa.com/product-category/lattafa-perfumes/page/10/
- https://lattafa.com/product-category/lattafa-perfumes/page/12/
- https://lattafa.com/product-category/lattafa-perfumes/page/13/

### Quality and scope notes

- Page 9 of 13 remains unchecked because the official page request timed out; page 1 was previously sampled and pages 3 and 11 were reviewed in pass 8.
- The current Lattafa bucket is 138 listing-level identities. This is not a claim that Lattafa's complete global fragrance range contains exactly 138 perfumes.
- The official archive includes line/collection labels such as Give Me Gourmand and Thameen Collection. They are retained under Lattafa because the official Lattafa Perfumes archive lists them, but product-level brand/line taxonomy still needs confirmation.
- A duplicate-key audit of the full catalog surfaced three pre-existing brand + normalized-name collisions outside Lattafa: two Afnan 9 AM/9 PM Pour Femme spelling variants, and Giorgio Armani Acqua di Gio Profondo with/without accent. No new duplicate brand/name key was introduced by this pass. These existing collisions should be reconciled before claiming a globally duplicate-free catalog.

### Pass 9 outcome

- New Lattafa identities added: 96.
- Lattafa bucket: 138.
- Total canonical product identities: 1503.
- Variant records retained: 141.
- Product IDs remain unique; no new duplicate brand + normalized-name pairs introduced.
- Page 9 remains open; no completeness claim is made.



## Latest independent validation and live-source review — 2026-11-07

### Exact branch snapshot revalidated

Re-read `backend/product_catalog.json` from branch `catalog/complete-brand-expansion-2026-11` and parsed the complete JSON payload.

- Product identity records: **1,503**
- Variant records: **141**
- Brand labels represented: **21** (20 requested brands/lines plus the pre-existing Giorgio Armani records)
- Product IDs duplicated: **0**
- Records without `source_url`: **0**
- Identity status: **33 source_verified_name**, **1,470 source_listed_name**
- Duplicate normalized brand + canonical-name keys: **3 pre-existing collisions**, listed below.

The three collisions are not new additions from this expansion and must be resolved or explicitly represented as aliases before the catalog can be called duplicate-clean:
1. Afnan — `9 AM Pour Femme`: `SH-AFNAN-5de78540` and `SH-AFNAN-9-AM-POUR-FEMME-E036`.
2. Afnan — `9 PM Pour Femme`: `SH-AFNAN-dec689ab` and `SH-AFNAN-9-PM-POUR-FEMME-E035`.
3. Giorgio Armani — `Acqua di Gio Profondo`: `SH-0043` and `SH-AUTO-0019`.

The catalog has source URLs on every record, but a source URL alone does not prove that the specific product page was checked or that all commercial attributes are verified.

### Additional live-source observations

#### Paris Corner — incomplete / taxonomy reconciliation required

- The official Paris Corner site separates distinct labels including **Paris Corner, North Stag, Emir, Ministry of Gourmand, Pendora Scents and Ministry of Oud**. These must not all be collapsed into the core Paris Corner brand without product-level attribution.
- The official European shop also displays separate brands/labels (Paris Corner, Emir, Ministry of Gourmand and Ministry of Oud).
- A current independent perfume index lists 205 Paris Corner fragrances, but it is a secondary database, not an official manufacturer inventory. It is useful as a gap-finding cross-check, not a target count.
- Current ScentHunter core-brand bucket: 120 records. This is not reconciled and must not be called complete.

Sources:
- Official brand taxonomy and product listings: https://www.pariscornerperfumes.com/
- Official Emir collection: https://www.pariscornerperfumes.com/collections/emir-1
- Official European shop: https://it.pariscornereurope.com/en
- Secondary cross-check only: https://www.fragrantica.com/designers/PARIS-CORNER.html

#### Khadlaj — incomplete / mixed product formats

- The official all-collections page reports 308 items across all products, but the same site separates air fresheners, bakhoor, home/ambience, gift sets, perfume oils, perfume sprays and other categories.
- The official page separately lists 88 items in the Khadlaj perfume-spray collection and 43 items in a concentrated-perfume-oil collection. These are category counts, not a deduplicated count of unique perfume identities.
- A current secondary fragrance database lists 147 Khadlaj perfumes. This is a useful cross-check but is not the manufacturer's master catalog.
- Current ScentHunter Khadlaj bucket: 44 records. A complete reconciliation is still required across perfume sprays, EDP/extrait, oils and sub-collections, with format kept distinct.

Sources:
- Official collections: https://khadlaj-perfumes.com/collections
- Official Saudi shop: https://khadlaj-perfumes.sa/
- Secondary cross-check only: https://www.fragrantica.com/designers/Khadlaj-Perfumes.html

#### Brand coverage status

Status below describes evidence reviewed so far, not whether the brand label exists in the JSON.

- **Partial / further source reconciliation required:** Paris Corner, Khadlaj, Maison Asrar, Armaf, Lattafa, Afnan, Swiss Arabian, Maison Alhambra, Assaf, Bujairami, French Avenue, Arabiyat Prestige, Gulf Orchid, Al Wataniah, Zimaya, Al Haramain.
- **Present, but full official-range reconciliation not yet demonstrated:** Velixir, Mykonos, Games of Spades, Aromatix.
- No requested brand should be marked **complete** based only on the present evidence.

This status is deliberately conservative. It is better to report an open gap than to imply a complete global range from a partial page sample or a retailer's current stock.

### Required next work before approval

1. Reconcile the three duplicate normalized keys. Select one canonical record per identity and retain alternate spellings/IDs as aliases or migration mappings; do not delete IDs that may already be referenced by other data without checking dependencies.
2. For Paris Corner, compare all paginated official product handles and product pages, with a separate namespace for each official sub-label.
3. For Khadlaj, reconcile perfume spray, EDP/extrait, and oil formats independently; exclude home/ambience, air freshener, bakhoor and gift bundles from standalone perfume identities unless explicitly modeled as such.
4. For Maison Asrar, finish a fragrance-only product-level reconciliation, explicitly checking Royal Collection members and excluding room/home fragrance.
5. For the remaining requested brands, create a per-brand evidence table with official source, pages checked, product-level records matched, missing candidates, ambiguous records and excluded non-perfume formats.
6. Run the catalog parser, seed dry-run validation, duplicate-key audit and connector-independent tests against this exact branch after any data change.
7. Keep PR #426 in draft until these gates pass. Do not merge it, PR #424, or deploy catalog changes to production as part of this work.

### Current conclusion

The branch is a substantial catalog expansion and the JSON parses cleanly. It has **1,503 identities and 141 variants**, but still contains three normalized identity collisions and incomplete source reconciliation. It is suitable for continued review on the isolated branch, not yet for a claim of a complete, production-ready fragrance catalog.



## Targeted Royal Collection and duplicate-identity follow-up — 2026-11-07

### Maison Asrar — Royal Collection checked against the official collection page

The official Maison Asrar Royal Collection page currently lists nine perfume identities:
- Belgravia
- Legacy
- Vanguard
- Regent
- Majesty
- Heritage
- Monarch
- Treasure
- Imperial

A name-level comparison against the current Maison Asrar bucket in `backend/product_catalog.json` confirms **9/9 are already present**. No duplicate Royal Collection rows were added. This resolves the specific Royal Collection coverage request at the visible collection-listing level; it does not certify the entire Maison Asrar range as complete.

Official source: https://maisonasrar.com/collections/royal-collection

Product-level official sources also exist for Heritage, Monarch, Treasure and Imperial:
- https://maisonasrar.com/products/maison-asrar-heritage-eau-de-parfum-100-ml-unisex
- https://maisonasrar.com/products/maison-asrar-monarch-eau-de-parfum
- https://maisonasrar.com/products/maison-asrar-treasure-eau-de-parfum-100-ml-unisex
- https://maisonasrar.com/products/maison-asrar-imperial-eau-de-parfum

The UK site also lists “The Royal” and a “Royal Collection Discovery Set”. These are bundle/set SKUs, not additional standalone perfume identities, so they must not be imported as individual fragrances. Sources:
- https://maisonasrar.co.uk/products/the-royal
- https://maisonasrar.co.uk/products/royal-collection-discovery-set

### Afnan — official 9 AM / 9 PM collection confirms the two duplicate pairs

The official Afnan collection page currently displays the standalone names exactly as:
- **9 AM - Pour Femme**
- **9 PM - Pour Femme**

The catalog contains two records for each name, differing only in punctuation and generated product ID. These are duplicate canonical identities, not four distinct fragrances. The same official collection page also contains gift-set products, which must remain separate from standalone fragrance identities.

Official source: https://afnan.com/collections/9am-9pm

The two duplicate pairs should be collapsed to one canonical fragrance record each after adding explicit legacy-ID migration support. Do not simply delete the extra product IDs: downstream code may reference them, and `legacy_product_id_map` must continue resolving old IDs to the canonical fragrance.

### Giorgio Armani — one fragrance identity, multiple package variants

The two existing Acqua di Gio Profondo records point to the same fragrance name and concentration (Eau de Parfum), with different package formats:
- 75 ml and 125 ml standard formats
- 100 ml refillable bottle

These should be represented as one canonical fragrance identity with three distinct variants, not two fragrance identities. The current variants list assigns the 75 ml and 125 ml formats to `SH-0043` and the 100 ml refillable format to `SH-AUTO-0019`.

Do not merge these records until the migration path preserves both legacy product IDs and all three variant IDs. The seed script currently maps each catalog product ID separately; it has no documented `legacy_product_ids` alias field yet. The correct fix therefore requires a small, tested schema/seed-script enhancement, not a cosmetic name edit.

Evidence:
- Standard EDP 125 ml: https://www.parfum-zentrum.de/giorgio-armani-acqua-di-gio-profondo-eau-de-parfum-125-ml-man_z771966/
- Refillable EDP 100 ml: https://www.parfum-zentrum.de/giorgio-armani-acqua-di-gio-profondo-eau-de-parfum-nachfullbar-100-ml-man_z947818/

### Updated resolution status

- Maison Asrar Royal Collection: **9/9 listed standalone perfume names already present**.
- Afnan 9 AM / 9 PM Pour Femme: **two duplicate identity pairs confirmed**; consolidation pending legacy-ID-safe migration.
- Giorgio Armani Acqua di Gio Profondo: **one fragrance identity with three package variants**; consolidation pending legacy-ID-safe migration.
- Catalog product IDs remain unique as stored; normalized identity audit still reports three duplicate-key groups. No records or IDs were deleted in this pass.
- No live retailer offers, prices, stock or shipping data were added.


## Seed/migration regression coverage — 2026-11-07

The seed script already resolves products to an existing fragrance by normalized brand + slug. Therefore duplicate source product IDs with punctuation/accent variations can map to the same fragrance while retaining separate legacy product-ID mappings and package variants. This behavior is now protected by a dedicated regression test in `tests/test_phase2_seed_catalog.py` for:
- Afnan 9 AM Pour Femme duplicate IDs;
- Afnan 9 PM Pour Femme duplicate IDs;
- Giorgio Armani Acqua di Gio / Giò Profondo duplicate IDs;
- 75 ml, 125 ml and 100 ml refillable variants retained under the same fragrance UUID.

The real-catalog dry-run test expectations were also updated to the exact current branch snapshot: 1,503 product identities, 141 variants, 21 normalized brand identities and 1,384 products without declared variants. The latter is a data-coverage indicator, not permission to infer sizes or variants.

The regression tests have been committed but **have not yet been executed in GitHub Actions**. Do not treat them as passing until a CI run reports success.


## Requested-brand and Royal Collection regression gates — 2026-11-07

Added two more regression tests to `tests/test_phase2_seed_catalog.py`:

1. The catalog must retain all 20 requested brands/lines, exactly 1,503 product rows and 141 explicit variant rows at this snapshot, with unique product/variant IDs, no orphan variants, HTTPS source URLs, recognized source-evidence states and no embedded offer price/stock.
2. Maison Asrar must retain all nine officially listed standalone Royal Collection fragrances, exactly once per name.

The assertions were cross-checked directly against the current JSON data in the GitHub branch. They are committed, but no passing CI run has been observed yet. These tests are snapshot guards, not a substitute for verifying that every brand's full current range is complete.



## Official Khadlaj perfume-spray listing reconciliation — 2026-11-07

Reviewed the official Khadlaj **Perfume Sprays** collection and its pagination. The collection page reports 101 products. The page reader exposed 96 product listings across pages 1–8; the final five listings on page 9 were not rendered in the retrieved page text and remain a known gap. The official site separately identifies perfume oils, home/ambiance, bakhoor, air fresheners and gift sets; those categories were not mixed into this perfume-spray pass.

Compared the 96 visible official listing names against current canonical names and aliases in ScentHunter. Added **69 missing fragrance identity candidates** to `backend/product_catalog.json`; the remaining visible names were already represented by canonical names or aliases. The additions are marked `source_listed_name`, point to their corresponding official paginated collection URL, and deliberately contain no inferred size, concentration, GTIN, price, stock, or variant rows.

The 69 added names include:
- Icon, Strawberry Shake, Peach Velvet, Mansion, Private Blend, Azure Velvet, Maison L'Imaginaire, Saqr Al Badiya, Opus Reborn, Musk Pour Amber, Fursan Brown.
- Le Prestige King/Royal/Empress/Bold; The Proposal Date Night/Special Occasion; Khadlaj 25 Experience/Trust/Loyalty/Heritage/Integrity.
- Valor Mystique/Honor/Chivalry/Enigma; Empire Empress/Crown/Regent; Karus Blu Spice/Oud Fire/Amber Gold.
- Maison Creation De Reve, Maison Epoque Artistique, Maison L'Or Noir, Maison Flor Oud, Wild Indonesian Oud, Mystical Indian Oud Pure, Oud Pour Noble/Shaikh/Rouge/Blueberry, Musk Pour Narcis, and additional listed spray fragrances.

Updated exact branch snapshot after this pass:
- Product identities: **1,581** (was 1,503)
- Explicit variant records: **141** (unchanged)
- Khadlaj identities: **113** (was 44)
- Products without explicitly declared variants: **1,453** (was 1,384)

The catalog remains a list of canonical identity candidates, not proof that the whole Khadlaj range is complete. In particular, the five not-extracted page-9 products and the separate Khadlaj perfume-oil collections remain unreviewed. No retailer offers or production data were changed.

Official sources:
- https://khadlaj-perfumes.com/collections/perfumes-spray
- https://khadlaj-perfumes.com/collections/perfumes-spray?page=2
- https://khadlaj-perfumes.com/collections/perfumes-spray?page=3
- https://khadlaj-perfumes.com/collections/perfumes-spray?page=4
- https://khadlaj-perfumes.com/collections/perfumes-spray?page=5
- https://khadlaj-perfumes.com/collections/perfumes-spray?page=6
- https://khadlaj-perfumes.com/collections/perfumes-spray?page=7
- https://khadlaj-perfumes.com/collections/perfumes-spray?page=8


## Paris Corner core collection — official page and size reconciliation pass

Reviewed the official core-brand collection (not the all-brands collection). The current page reports **105 products** and the site maintains separate collection labels for Paris Corner, North Stag, Emir, Pendora, Ministry of Oud and other lines. Those sub-brands must remain separately attributed where the product page identifies them. Pages 1–3 exposed 96 product names; page 4 exposed the final nine, bringing the verified listing set to all 105 current collection entries. All 105 official names were compared against the ScentHunter `Paris Corner` bucket. The first 96 were already represented by existing canonical names; the final nine were absent and have now been added. Six existing identities were missing their explicit 100ml package variant.

Added six 100ml variants, each linked to its official product-detail page:
- Confidential — `/products/confidential-100ml`
- Khayal — `/products/khayal-100ml`
- Minya — `/products/minya-100ml`
- Ophidian Black Cherry — `/products/ophidian-black-cherry-100ml`
- Qawafi — `/products/qawafi-100ml`
- Taskeen Lactea Divina — `/products/taskeen-lactea-divina-100ml`

This reconciliation adds **9 product identities and 6 explicit variants**. Product-level `source_evidence_url` now points to the official product page. No concentration, price, stock or offer data was inferred.

Updated current branch snapshot:
- Product identities: **1,572**
- Explicit variants: **147** (previously 141)
- Products without declared variants: **1,456** (previously 1,447)

A regression test now asserts all six official 100ml variants and their product evidence URLs. All 105 currently listed official core-brand names are now represented in the catalog. The 129-record Paris Corner bucket is still 24 records larger than the current 105-item collection; those additional records need review for discontinued products, legacy names, and possible product-line misattribution. This is a current-collection name match, not proof that the complete historical range has been captured.

Official sources:
- https://www.pariscornerperfumes.com/collections/paris-corner
- https://www.pariscornerperfumes.com/collections/paris-corner?page=2
- https://www.pariscornerperfumes.com/collections/paris-corner?page=3
- https://www.pariscornerperfumes.com/products/confidential-100ml
- https://www.pariscornerperfumes.com/products/khayal-100ml
- https://www.pariscornerperfumes.com/products/minya-100ml
- https://www.pariscornerperfumes.com/products/ophidian-black-cherry-100ml
- https://www.pariscornerperfumes.com/products/qawafi-100ml
- https://www.pariscornerperfumes.com/products/taskeen-lactea-divina-100ml


### Paris Corner page 4 — final nine current collection names

Page 4 of the official core-brand collection exposed the final nine names: **Virilis, Zahi, Zahri Amara, Zaman Al Ula, Zariya, Zodiac, Zodiac Lunaris, Zodiac Solmaris and Zodiac Stratos**. None existed in the prior Paris Corner canonical-name/alias set, and all nine were added as `source_listed_name` identities with the official page-4 collection URL. This closes the current 105-name visible collection comparison at the name level.

Updated branch snapshot after page 4:
- Product identities: **1,581** (up from 1,572)
- Variants: **147**
- Paris Corner identities: **129** (up from 120)
- Current official core-brand collection: **105/105 listed names represented**
- Additional Paris Corner catalog identities beyond the current collection: **24**, to be classified as legacy/discontinued or re-attributed after product-level review.

Source: https://www.pariscornerperfumes.com/collections/paris-corner?page=4


## Armaf official US fragrance-listing pass — pages 1–4

Reviewed the official ARMAF US collection **All Fragrances (Not Gift Set)** and the first four currently surfaced pages. The collection's live page reports 424 listings and its concentration filters include EDP, EDT, Extrait and Parfum alongside body sprays, mists, lotions, deodorants, roll-ons, shower gels and soaps. Therefore the raw collection count is not a perfume-identity count and must not be imported wholesale.

Compared visible product names from the first six pages against the existing Armaf catalog. Eight official perfume identities were missing and have been added with product-detail evidence URLs and verified concentrations:
- Odyssey Bloody Hot — Eau de Parfum
- Odyssey Ring My Bell — Eau de Parfum
- Eter Arabian Sky — Eau de Parfum
- Odyssey French Kiss — Eau de Parfum
- Odyssey Pink Pop — Eau de Parfum
- Spartacus — Eau de Parfum
- Odyssey Soda Pop — official fragrance identity (concentration not inferred from the detail page)
- Club de Nuit Iconic Extrait de Parfum — Extrait de Parfum

Also reconciled two official names to existing canonical records instead of creating duplicates:
- Club de Nuit Precieux 1 Extrait de Parfum maps to the existing Club de Nuit Precieux I identity; official page confirms Extrait de Parfum and 55ml, so the 55ml variant is now explicit.
- Club de Nuit Woman Extrait de Parfum maps to the existing Club de Nuit Woman Extrait identity; its official concentration and product evidence URL are now recorded.

Added a 70ml variant for Club de Nuit Iconic Extrait de Parfum from the official product description. No prices, stock or retailer offers were added.

Updated branch snapshot:
- Product identities: **1,589** (up from 1,581)
- Explicit variants: **149** (up from 147)
- Armaf identities: **247** (up from 239)
- Products without declared variants: **1,462**

This is a partial Armaf pass only. Six pages of a large, mixed-format official collection do not establish full Armaf coverage. The remaining pages, product types and any further concentration/size variants still need reconciliation. The 424 collection count includes non-perfume body-care items and must be filtered by product type before completeness can be measured.

Official sources:
- https://armaf.com/collections/all-fragrances-not-gift-set
- https://armaf.com/products/odyssey-bloody-hot
- https://armaf.com/products/odyssey-ring-my-bell
- https://armaf.com/products/eter-arabian-sky
- https://armaf.com/products/odyssey-french-kiss
- https://armaf.com/products/odyssey-pink-pop-edp
- https://armaf.com/products/spartacus-edp
- https://armaf.com/products/club-de-nuit-iconic-estrait-de-parfum
- https://armaf.com/products/club-de-nuit-precieux-1-extrait-de-parfum-55ml
- https://armaf.com/products/cdn-club-de-nuit-extrait-de-parfum-spr


Page 6 also exposed **Odyssey Soda Pop**, which was absent from the Armaf bucket. Added it as a source-verified fragrance identity with its official product-detail URL. Its concentration and size were left unset because the retrieved product detail did not state them. Source: https://armaf.com/products/odyssey-soda-pop
