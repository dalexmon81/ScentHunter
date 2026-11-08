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
Current catalog snapshot: **1,645 canonical product identity records; 171 variant records; 21 brand labels** (revalidated 2026-11-07). The full request is represented at the brand-label level, but this is not an exhaustive global catalogue reconciliation.

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

Compared visible product names from the first twelve pages against the existing Armaf catalog. Seventeen official fragrance identities were missing and have been added with product-detail evidence URLs and verified concentrations:
- Odyssey Bloody Hot — Eau de Parfum
- Odyssey Ring My Bell — Eau de Parfum
- Eter Arabian Sky — Eau de Parfum
- Odyssey French Kiss — Eau de Parfum
- Odyssey Pink Pop — Eau de Parfum
- Spartacus — Eau de Parfum
- Odyssey Soda Pop — official fragrance identity (concentration not inferred from the detail page)
- Uniq Effects of Uniq — official fragrance identity (concentration not inferred)
- Scentasy Noir De Peche — official fragrance identity (concentration not inferred)
- Kunafa Chocolate — Eau de Parfum
- Dubai Nights Midnight — official fragrance identity (concentration not inferred)
- Mirage Woman — Eau de Parfum
- Voyage Brown Man — Eau de Parfum
- Club de Nuit Private Key To My Life — Eau de Toilette
- Club de Nuit Woman Parfum Extreme Edition — Parfum
- Niche Purple Amethyst Fleur — Eau de Parfum
- Club de Nuit Iconic Extrait de Parfum — Extrait de Parfum

Also reconciled two official names to existing canonical records instead of creating duplicates:
- Club de Nuit Precieux 1 Extrait de Parfum maps to the existing Club de Nuit Precieux I identity; official page confirms Extrait de Parfum and 55ml, so the 55ml variant is now explicit.
- Club de Nuit Woman Extrait de Parfum maps to the existing Club de Nuit Woman Extrait identity; its official concentration and product evidence URL are now recorded.

Added a 70ml variant for Club de Nuit Iconic Extrait de Parfum from the official product description. No prices, stock or retailer offers were added.

Updated branch snapshot:
- Product identities: **1,598** (up from 1,581)
- Explicit variants: **151** (up from 147)
- Armaf identities: **256** (up from 239)
- Products without declared variants: **1,469**

This is a partial Armaf pass only. Twelve pages of a large, mixed-format official collection do not establish full Armaf coverage. The remaining pages, product types and any further concentration/size variants still need reconciliation. The 424 collection count includes non-perfume body-care items and must be filtered by product type before completeness can be measured.

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


Pages 7–8 yielded four more product-detail-confirmed Armaf fragrance identities absent from the catalog: **Uniq Effects of Uniq, Scentasy Noir De Peche, Kunafa Chocolate and Dubai Nights Midnight**. Added them with official product-detail evidence. Concentration remains unset for three because the retrieved detail pages did not state it; Kunafa Chocolate is explicitly Eau de Parfum. Sources:
- https://armaf.com/products/uniq-effects-of-uniq-spr
- https://armaf.com/products/scentasy-noir-de-peche
- https://armaf.com/products/kunafa-chocolate
- https://armaf.com/products/dubai-nights-midnight-spr


Pages 9–10 added three further product identities confirmed by official detail pages: **Mirage Woman** (Eau de Parfum), **Voyage Brown Man** (Eau de Parfum) and **Club de Nuit Private Key To My Life** (Eau de Toilette). The latter has an official 100ml variant, now explicit. Three displayed names were mapped to existing identities rather than duplicated: The Lion's Club Monarque, Craze Man Parfum and Club de Nuit Urban. Their aliases/evidence were updated. Official product sources:
- https://armaf.com/products/mirage-woman
- https://armaf.com/products/voyage-brown
- https://armaf.com/products/club-de-nuit-private-key-to-my-life-100ml
- https://armaf.com/products/the-lions-club-monarque
- https://armaf.com/products/armaf-craze
- https://armaf.com/products/club-de-nuit-iconic


Pages 11–12 yielded two additional concentration-specific products confirmed by the official detail pages: **Club de Nuit Woman Parfum Extreme Edition** (Parfum, 105ml) and **Niche Purple Amethyst Fleur** (Eau de Parfum). Both are now separate canonical identities; the 105ml variant is explicit for the former. Official sources:
- https://armaf.com/products/club-de-nuit-woman-parfum-extreme-edition
- https://armaf.com/products/niche-purple-amethyst-fleur


## Armaf official US collection — additional pages 13–26

Continued the listing-level comparison on the official US **All Fragrances (Not Gift Set)** collection. The retrieved pages 13–26 show a mixture of perfume products and body-care items. Only entries identified as perfume products were added; body sprays, lotions, deodorants, roll-ons, shower gels, soaps, gift sets and discovery bundles were not imported as perfume identities.

Added **30 fragrance identities** absent from the existing Armaf catalog:
- Art Du'Parfum Abstracto; The Lion's Club Courageux; El Cielo Man; Hunter Killer Man; Oros Pure Cloisonne; Tag Her Donna Colorata Purple
- Vanity Femme Essence Woman; Amber Arabia Oud; Eter Desert Breeze; Oros The Inventor Black; Profumi D'Art 03 Legni Dolci Bruciati; Odyssey Wild One; Odyssey Aoud; Connoisseur Woman; Magnificent Satin
- Eternia Man; Eternia Man Limited Edition; Red Velvet; Miss Armaf Magnifiq; SHK IV by Saoud Alkaabi; Red Sky; Bucephalus No. X; Niche Platinum; Le Parfait Azure Femme
- Magnificent Pour Femme; Let's Move Tango; Magnificent Jardin; Club de Nuit Intense Man Parfum Extreme Edition; Blue Sky; Blue Homme

Each entry is recorded as `source_listed_name` with its official collection page as evidence. Concentration is populated only where the official listing states it; it remains unset for Eternia Man Limited Edition because the listing did not expose one. No sizes, prices or stock were inferred.

Updated branch snapshot:
- Product identities: **1,628** (up from 1,598)
- Explicit variants: **151**
- Armaf identities: **286** (up from 256)
- Products without declared variants: **1,477**

This is a page-sample reconciliation, not a claim that all Armaf products have been imported. The collection pagination is dynamic and contains mixed product formats; remaining pages, duplicate name/size variants and official product-detail evidence still require review.

Official sources:
- https://armaf.com/collections/all-fragrances-not-gift-set?page=13
- https://armaf.com/collections/all-fragrances-not-gift-set?page=14
- https://armaf.com/collections/all-fragrances-not-gift-set?page=15
- https://armaf.com/collections/all-fragrances-not-gift-set?page=16
- https://armaf.com/collections/all-fragrances-not-gift-set?page=17
- https://armaf.com/collections/all-fragrances-not-gift-set?page=18
- https://armaf.com/collections/all-fragrances-not-gift-set?page=19
- https://armaf.com/collections/all-fragrances-not-gift-set?page=20
- https://armaf.com/collections/all-fragrances-not-gift-set?page=22
- https://armaf.com/collections/all-fragrances-not-gift-set?page=23
- https://armaf.com/collections/all-fragrances-not-gift-set?page=24
- https://armaf.com/collections/all-fragrances-not-gift-set?page=26


## Latest branch reconciliation — additional Armaf detail-page records

A fresh read of the shared PR branch showed eight additional Armaf identities and five explicit size variants beyond the previous page-listing batch. Their official product detail pages were checked and the test snapshot was brought into line with the actual branch state:
- Club de Nuit Private Key To My Success — Eau de Parfum, 100ml
- Miss Armaf Dazzling — Eau de Parfum, 100ml
- Checkmate White Knight — Eau de Parfum
- Tag Him Prestige — concentration left unset because the detail page does not state it
- Club de Nuit Private Key To My Love — Eau de Toilette, 100ml
- Dubai Nights Umbra — concentration left unset because the detail page does not state it
- Oros The Inventor Brown — Eau de Parfum, 85ml
- Ego Tigre — Eau de Parfum, 100ml

Updated current branch snapshot:
- Product identities: **1,636**
- Explicit variants: **156**
- Armaf identities: **294**
- Products without declared variants: **1,502**

The eight records have official product-detail evidence URLs. Concentrations and sizes are retained only where the official pages state them. Sources:
- https://armaf.com/products/copy-of-club-de-nuit-private-key-to-my-success-100ml
- https://armaf.com/products/miss-armaf-dazzling
- https://armaf.com/products/checkmate-white-knight-1
- https://armaf.com/products/tag-him-prestige
- https://armaf.com/products/club-de-nuit-private-key-to-my-love-100ml
- https://armaf.com/products/dubai-nights-umbra-spr
- https://armaf.com/products/the-inventor
- https://armaf.com/products/ego-tiger


## Armaf official US collection pages 13–16 — further detail-page reconciliation

Continued the official ARMAF US “All Fragrances (Not Gift Set)” review. The listing mixes fragrance products with body sprays, roll-ons, shower gels and other care products; those non-perfume formats are not automatically imported as canonical fragrance identities.

Added eight missing fragrance identities after confirming their official product-detail pages:
- Club de Nuit Private Key To My Success — Eau de Parfum, 100ml
- Miss Armaf Dazzling — Eau de Parfum, 100ml
- Checkmate White Knight — Eau de Parfum (size not stated on the retrieved detail page)
- Tag Him Prestige — identity verified; concentration and size not stated
- Club de Nuit Private Key To My Love — Eau de Toilette, 100ml
- Dubai Nights Umbra — identity verified; concentration and size not stated on the retrieved detail page
- Oros The Inventor Brown — Eau de Parfum, 85ml
- Ego Tigre — Eau de Parfum, 100ml

The official product page for Ego Tigre has an inconsistent SEO title/slug, but its page heading and product content identify the fragrance as **Ego Tigre**; the canonical name follows the on-page product heading. No unsupported concentration or size was assigned to Tag Him Prestige or Dubai Nights Umbra.

Updated snapshot:
- Product identities: **1,636** (up from 1,628)
- Explicit variants: **156** (up from 151)
- Armaf identities: **294** (up from 286)
- Products without declared variants: **1,502**
- No orphan variants; product IDs and variant IDs remain unique.

Official detail pages:
- https://armaf.com/products/copy-of-club-de-nuit-private-key-to-my-success-100ml
- https://armaf.com/products/miss-armaf-dazzling
- https://armaf.com/products/checkmate-white-knight-1
- https://armaf.com/products/tag-him-prestige
- https://armaf.com/products/club-de-nuit-private-key-to-my-love-100ml
- https://armaf.com/products/dubai-nights-umbra-spr
- https://armaf.com/products/the-inventor
- https://armaf.com/products/ego-tiger

This extends the sample, but does not prove that all Armaf fragrance pages or variants have been captured.


## Armaf official US collection pages 17–20 — two further product identities

The page 17–20 listing sample surfaced two additional fragrance identities missing from the catalog and confirmed by official product-detail pages:
- **Ombre Oud Intense Black** — Eau de Parfum, 100ml
- **Eter Desert Rose** — Eau de Parfum; the retrieved detail page did not state a size, so no variant was inferred.

Both are now represented with official product evidence URLs. The catalog snapshot is now **1,643 identities, 160 variants, 301 Armaf identities**. Products without declared variants: **1,505**.

Official detail pages:
- https://armaf.com/products/ombre-oud-intense-black
- https://armaf.com/products/eter-desert-rose

The Armaf audit remains a partial reconciliation; the source collection is dynamic and mixes fragrance products with body-care items and bundles.


## Armaf official pages 13–20 — missing identities and explicit 100ml sizes

Reviewed official collection pages 13–20 and compared fragrance listings with the current Armaf catalog. Most displayed fragrances were already represented. Five missing names were added with product-detail evidence:
- **Eter Perfume Oasis** — Eau de Parfum
- **Club de Nuit Private Key To My Dreams** — Eau de Toilette, 100ml
- **Club de Nuit Private Key To My Soul** — Eau de Parfum, 100ml
- **Niche Sapphire** — fragrance identity retained without an inferred concentration
- **Profumi D'Art 13 Tanta Roba** — Eau de Parfum, 100ml

Three explicit 100ml variant records were added for the two Private Key fragrances and Profumi D'Art 13. Eter Perfume Oasis and Niche Sapphire have no inferred size. No prices, stock or offers were imported.

Current branch snapshot after this pass:
- Product identities: **1,643**
- Explicit variants: **160**
- Armaf identities: **301**
- Products without declared variants: **1,505**

This remains a partial collection reconciliation. The official ARMAF collection mixes fragrances with body sprays, shower gels, deodorants and other body-care formats; only fragrance identities were included in this pass. Further pages and line-specific collections still require filtering and deduplication.

Official sources:
- https://armaf.com/collections/all-fragrances-not-gift-set?page=13
- https://armaf.com/collections/all-fragrances-not-gift-set?page=14
- https://armaf.com/collections/all-fragrances-not-gift-set?page=15
- https://armaf.com/collections/all-fragrances-not-gift-set?page=16
- https://armaf.com/collections/all-fragrances-not-gift-set?page=17
- https://armaf.com/collections/all-fragrances-not-gift-set?page=18
- https://armaf.com/collections/all-fragrances-not-gift-set?page=19
- https://armaf.com/collections/all-fragrances-not-gift-set?page=20
- https://armaf.com/products/eter-perfume-oasis
- https://armaf.com/products/club-de-nuit-private-key-to-my-dreams-100ml
- https://armaf.com/products/club-de-nuit-private-key-to-my-soul-100ml
- https://armaf.com/products/niche-saphire
- https://armaf.com/products/profumi-dart-13-e-tanta-roba


## Armaf official US collection pages 22–24 — four more fragrances and two 200ml formats

Four additional official fragrance identities were missing from the catalog and have now been added with product-detail evidence:
- **Oros Uomo** — Eau de Parfum, 100ml
- **Art Du' Parfum Pour Homme** — Eau de Parfum; size not converted because the official page lists 3.6 oz rather than a metric size
- **Radical Blue Man** — Eau de Parfum, 100ml
- **Oros Oud** — Eau de Parfum, 85ml

The existing **Club de Nuit Private Key To My Soul** identity was already added in a concurrent branch update and now has its 100ml variant. Two existing Le Parfait identities have also gained verified 200ml variants:
- Le Parfait Panache — 200ml
- Le Parfait Azure Femme — 200ml

Updated branch snapshot:
- Product identities: **1,647**
- Explicit variants: **165**
- Armaf identities: **305**
- Products without declared variants: **1,504**

Official detail pages:
- https://armaf.com/products/oros-uomo
- https://armaf.com/products/art-du-parfum
- https://armaf.com/products/radical-edp-for-men-slate-blue-btl
- https://armaf.com/products/oros-oud
- https://armaf.com/products/club-de-nuit-private-key-to-my-soul-100ml
- https://armaf.com/products/le-parfait-panache-1
- https://armaf.com/products/le-parfait-azure-pour-femme-1

This is still a sampled reconciliation of the dynamic official collection, not a completeness claim.


### Branch-head snapshot reconciliation

The branch advanced while the page-13–20 pass was being committed. Re-read the actual branch head and reconciled the snapshot assertions to the authoritative current file: **1,647 identities, 165 variants, 305 Armaf identities, 1,504 identities without variants**. Product IDs and variant IDs remain unique, and the three normalized duplicate groups are unchanged. These are branch-file counts only; the seed has not been imported into production.


## Maison Asrar Royal Collection source correction — 2026-11-07

A follow-up source check corrected an earlier over-broad collection attribution. The live Maison Asrar UK Royal Collection page is:
https://maisonasrar.co.uk/collections/royal-collection

That official page lists six individual fragrances — Belgravia, Legacy, Vanguard, Regent, Majesty and Heritage — plus two non-fragrance/bundle entries (Treasure and The Royal are listed as products on the page; Treasure is shown with fragrance notes, while The Royal is a bundle). The catalog now marks only the six individually listed fragrances with `collection_name: Royal Collection` and uses the correct official UK collection URL as evidence.

Monarch, Treasure and Imperial remain in the Maison Asrar identity catalog, but are no longer tagged as confirmed members of the official collection based on that page. They are retained as source-listed Maison Asrar names; their collection membership needs separate product-level confirmation. This avoids turning retailer taxonomy or an unverified URL into an official brand claim.

The previous `maisonasrar.com/collections/royal-collection` URL was not substantiated and has been removed from these records. This correction supersedes the earlier nine-name Royal Collection assertion.


## Maison Asrar Royal Collection — product-level correction, 2026-11-07

A deeper check of the official UK collection page and its linked product pages supersedes the prior six-fragrance note above. The page currently contains **seven individual fragrance identities**: Belgravia, Legacy, Vanguard, Regent, Majesty, Heritage and Treasure. Treasure is confirmed separately by its product detail page as a 100 ml Eau de Parfum. It is now tagged as part of Royal Collection, with its product page as `source_url` and the official collection page as `source_evidence_url`.

The other three entries on the collection page are not additional individual fragrance identities: **The Royal** is a bundle of Legacy, Majesty and Vanguard; **Royal Collection Discovery Set** is a discovery set; **The Royal Duo** is a bundle. They must not be imported as standalone canonical fragrances.

The earlier six-name claim omitted Treasure; the earlier nine-name claim included unsupported Monarch and Imperial and wrongly omitted Treasure. The corrected official collection count for individual fragrances is seven. Source pages:
- https://maisonasrar.co.uk/collections/royal-collection
- https://maisonasrar.co.uk/products/maison-asrar-treasure-eau-de-parfum-100-ml-unisex
- https://maisonasrar.co.uk/products/the-royal
- https://maisonasrar.co.uk/products/royal-collection-discovery-set
- https://maisonasrar.co.uk/products/the-royal-duo


## Khadlaj official perfume-spray reconciliation — 2026-11-07

A fresh review of the official Khadlaj shop separates the **Perfume Sprays** collection from perfume oils, bakhoor, home/ambiance products and gift sets. The current Perfume Sprays collection reports 101 products; the official collections index reports separate counts for Khadlaj Perfume Spray (88), La Fede EDP (42), perfume oils, home/ambiance and other categories. Counts overlap across promotional and line collections and must not be summed as unique fragrances.

The visible product cards sampled across the official Perfume Sprays pagination matched existing catalog identities after normalizing product-card names to canonical names. No new canonical identity was added from this pass. Seven existing records received product-level source reconciliation:
- **Musk Pure Musk Blend** — official detail page spells out “Musk Pure Musk Blend Creation of Iqbal”; retained as one identity, with the official title added as an alias. Existing 60 ml EDP variant retained.
- **Khadlaj 25 Experience, 25 Trust, 25 Loyalty, 25 Heritage and 25 Integrity** — exact official product pages confirm 100 ml Eau de Parfum; product source URLs, concentration, format and explicit 100 ml variants were added.
- **Wild Indonesian Oud** — official page title is “Wild Indonesian Oud Pure”, 60 ml Eau de Parfum; retained as one identity with the official full title as an alias and a 60 ml EDP variant.

Official collection:
https://khadlaj-perfumes.com/collections/perfumes-spray

Official product evidence:
- https://khadlaj-perfumes.com/collections/perfumes-spray/products/musk-pure-musk-blend-creation-of-iqbal-65-ml-edp-spray-perfume-for-men-and-women-online-dubai-uae
- https://khadlaj-perfumes.com/collections/perfumes-spray/products/khadlaj-25-experience-100-ml-edp-spray
- https://khadlaj-perfumes.com/collections/perfumes-spray/products/buy-khadlaj-25-trust-100-ml-edp-spray-best-gourmand-perfume-for-women
- https://khadlaj-perfumes.com/collections/perfumes-spray/products/khadlaj-25-loyalty-100-ml-edp-spray-best-women-perfume-to-shop-online-dubai-uae
- https://khadlaj-perfumes.com/collections/perfumes-spray/products/khadlaj-25-heritage-100-ml-edp-spray
- https://khadlaj-perfumes.com/collections/perfumes-spray/products/khadlaj-25-integrity-100-ml-edp-spray
- https://khadlaj-perfumes.com/collections/perfumes-spray/products/wild-indonesian-oud-spray-shop-online-best-price-in-dubai-uae

This is a product-level correction of existing identities and variant data, not a claim that all Khadlaj perfume oils, extracts, collections or regional products have been exhaustively reconciled.


## Current branch-head reconciliation — Khadlaj and Paris Corner, 2026-11-07

### Khadlaj

The official Perfume Sprays collection currently reports 101 products, distinct from the shop's perfume oils, bakhoor, home/ambiance and gift-set sections. The visible cards checked across the collection's pagination were reconciled to existing canonical identities; no new canonical identity was added in this pass.

Seven existing Khadlaj identities now have product-level official evidence. Five Khadlaj 25 fragrances have verified 100 ml Eau de Parfum variants (Experience, Trust, Loyalty, Heritage, Integrity); Wild Indonesian Oud Pure has a verified 60 ml Eau de Parfum variant; Musk Pure Musk Blend retains its existing 60 ml EDP variant and gains the full official product title as an alias. The catalog now records **113 Khadlaj identities** and the additional six variants are reflected in the current total.

### Paris Corner

The official /collections/paris-corner collection currently reports **104 products**. The broader /collections/all page currently reports **252 products** and explicitly lists distinct lines/brands including Paris Corner, Ministry of Oud, North Stag, Pendora, Emir and Magic Oud Series. These totals are not interchangeable and must not be used as counts of unique core Paris Corner perfumes.

The catalog currently has **129 records labelled Paris Corner**, but that count is not a defensible core-brand coverage figure. At least the following names in the broad all-products listing require a brand/line ownership check before they can be counted as core Paris Corner:
- Acadia Intenso Emir
- Camp Fire Emir Factory Edition
- Cedrat Essence Emir
- Celestial Emir
- North Stag Neuf IX

These records were **not** automatically reassigned. Their source listing proves they appear in the Paris Corner group's all-products catalog, but the separate brand navigation shows that group contains multiple lines. The exact line owner should be set only after checking each product detail page or its explicit brand label.

Official sources:
- https://www.pariscornerperfumes.com/collections/paris-corner
- https://www.pariscornerperfumes.com/collections/all
- https://khadlaj-perfumes.com/collections/perfumes-spray
- https://khadlaj-perfumes.com/collections

### Latest data snapshot and validation status

- Canonical product identities: **1,647**
- Explicit variant records: **171**
- Products without a declared variant: **1,498**
- Requested brand/line labels represented: **20 of 20**
- Product IDs unique; variant IDs unique; no orphan variants.

The first CI run after adding the six Khadlaj variants failed because two existing tests still asserted the previous snapshot (165 variants and 1,504 products without variants). Those assertions were updated to the actual catalog snapshot (171 and 1,498). The corrected CI run #180 completed successfully (schema-contract and schema/seed integration tests passed).


## Paris Corner official product-line tagging — 2026-11-07

A direct review of the official line collections confirms that **Emir, Pendora Scents, Ministry of Gourmand and North Stag are product lines/series under the Paris Corner parent brand**, not reasons to overwrite the parent brand field. The catalog therefore preserves `brand: "Paris Corner"` and records the verified line in `collection_name`.

This pass tagged 21 existing canonical identities using official collection membership:
- **Emir:** 10 identities — Acadia Intenso Emir, Arcana, Atomise Intensive Men, Camp Fire Emir Factory Edition, Cedrat Essence Emir, Celestial Emir, Cherry Cola, Cherry Gossip, Cosmopolitan Dubai, Cosmopolitan London.
- **Pendora Scents:** 6 identities — Attractus, Blackberry Wish, Camaro Homme Intense, Charuto Mysterious Tobacco, Charuto Regal Reserve, Cornflower Delight.
- **Ministry of Gourmand:** 4 identities — Banana Bliss, Cake Temptation, Choco Cult, Coconut Lagoon.
- **North Stag:** 1 identity — North Stag Neuf IX.

Each tagged identity now points to the corresponding official line collection as source and evidence. Regression coverage asserts the line tag, parent brand and official source URL. No product identity was added, removed or renamed in this pass.

Official collection sources:
- Emir: https://www.pariscornerperfumes.com/collections/emir-1
- Pendora Scents: https://www.pariscornerperfumes.com/collections/pendora-scents-1
- Ministry of Gourmand: https://www.pariscornerperfumes.com/collections/ministry-of-gourmand
- North Stag: https://www.pariscornerperfumes.com/collections/north-stag-1

This is a **partial line reconciliation**, not a claim that all 129 Paris Corner-labelled identities have been assigned to a verified product line. Other identities remain in the parent brand until their line membership is verified.


## Maison Asrar Royal Collection — current official-site reconciliation (2026-11-07)

A fresh check of the current official global Maison Asrar collection page supersedes the earlier UK-site snapshot. The current page lists **9 individual fragrance products** in Royal Collection: Belgravia, Legacy, Vanguard, Regent, Majesty, Monarch, Heritage, Imperial and Treasure. The earlier seven-product count reflected an older/different regional collection snapshot and is no longer the correct current global-site count.

The two already-existing catalog identities **Monarch** and **Imperial** are now tagged as `collection_name: "Royal Collection"`, and their source/evidence URLs point to the current official collection page. No new canonical identities were created; existing product IDs and variants were preserved. A regression test asserts the exact nine-name collection membership and evidence URL.

Official source: https://maisonasrar.com/collections/royal-collection

This is a live catalog snapshot and can change; future refreshes should compare the collection membership again rather than treating nine as permanent.


## Armaf catalog coverage — scope warning and next reconciliation (2026-11-07)

The current seed contains **305 canonical identities labelled Armaf**. The current official Armaf US "All Fragrances" collection reports **464 product listings**, but the same page's filters include Eau de Parfum, Eau de Toilette, extrait/parfum, body mist, body spray, deodorants, roll-ons, shampoo, shower gel, soap and other care formats. The listing count is therefore **not directly comparable** to 305 canonical fragrance identities: it includes non-fragrance care products and can include multiple concentrations/variants or sets.

No automatic gap-filling or deletions were made from the 464 listing count. The next Armaf audit must:
1. Define scope as standalone fragrance identities (include EDP/EDT/extrait as variants or distinct concentration variants according to canonical rules; exclude body care and gift/travel sets from fragrance identity count).
2. Extract official product names and detail URLs, deduplicate variants and bundles.
3. Match against the 305 current canonical identities by exact product identity, not loose name similarity.
4. Add only confirmed missing fragrances, with official detail-page evidence, and preserve existing product IDs/variant links.

Official source: https://armaf.com/collections/all-perfumes (current listing reports 464 products; filters visibly include fragrance and non-fragrance categories).

This count is a scope signal, **not evidence that 159 perfumes are missing**.


## Armaf official collection reconciliation — 2026-11-07

The current Armaf US official site separates fragrance collections and collaborations in its navigation. The catalog's 305 Armaf records were therefore not treated as one undifferentiated line. This pass tagged existing products against official collection pages, preserving `brand: "Armaf"` and recording the line in `collection_name`.

Verified collection pages used:
- Club de Nuit — https://armaf.com/collections/club-de-nuit
- Odyssey — https://armaf.com/collections/odyssey
- Tres Nuit — https://armaf.com/collections/armaf-tres-nuit-collection
- Checkmate — https://armaf.com/collections/checkmate
- Eter — https://armaf.com/collections/eter
- Bucephalus — https://armaf.com/collections/bucephalus
- Tag — https://armaf.com/collections/tag
- Armaf Delights — https://armaf.com/collections/armaf-delights
- The Lion's Club — https://armaf.com/collections/the-lions-club
- Profumi D'Art — https://armaf.com/collections/profumi-dart
- ARMAF X Christian Provenzano — https://armaf.com/collections/armaf-collection-for-christian-provenzano
- ARMAF X SHK — https://armaf.com/collections/shk
- Oros — https://armaf.com/collections/oros
- ARMAF Niche — https://armaf.com/collections/armaf-niche
- The Inventor — https://armaf.com/collections/armaf-the-inventor

The official ARMAF X Christian Provenzano page lists four products (I–IV), while the catalog previously contained only III and IV. Added I and II as source-listed canonical identities. The official ARMAF X SHK page lists I–IV, while the catalog previously contained I, III and IV. Added II. These new records have no size variants because the collection pages did not establish a specific size.

Five cross-region duplicate identities were consolidated, retaining the current official US product record and moving the alternate regional spelling into aliases. No variants were lost; all five removed identities had zero variants:
- Odyssey Lichi Lush → Odyssey Li'Chi Lush EDP (removed ID: SH-ARMAF-ODYSSEY-LICHI-LUSH-P333)
- Lion's Club Courageux → The Lion's Club Courageux (removed ID: SH-ARMAF-LION-S-CLUB-COURAGEUX-P334)
- Profumi D'Art 13 E Tanta Roba → Profumi D'Art 13 Tanta Roba (removed ID: SH-ARMAF-PROFUMI-D-ART-13-E-TANTA-RO-P015)
- Perfume Oasis For Eter → Eter Perfume Oasis (removed ID: SH-ARMAF-PERFUME-OASIS-FOR-ETER-P017)
- Desert Rose For Eter → Eter Desert Rose (removed ID: SH-ARMAF-DESERT-ROSE-FOR-ETER-P030)

The catalog now contains **303 Armaf identities** and **1645 total canonical identities**, with 171 explicit variants. The new snapshot tests verify the additions, collection tags, source URLs and alias consolidation. The remaining regional-name candidate **Tres Nuit Lyric Pour Homme** has not been merged with **Tres Nuit Lyric Man**; it remains flagged for product-level identity verification rather than being guessed.

Important scope note: the official `all-perfumes` page currently displays 464 listings, and the broader all-products page displays still more. Those are store listings, not a count of unique canonical perfume identities: they include product types, sets and sizes. Do not use those raw listing totals as the expected number of canonical fragrance records.


## Armaf pass — final branch snapshot after CI assertion correction

The catalog currently contains **1,645 canonical identities, 171 explicit variants, 1,496 products without declared variants and 303 Armaf identities**. This supersedes the earlier 1,647 / 305 snapshot after five duplicate regional spellings were consolidated and three official collection-listed fragrances were added. All five removed records had no variants, so the variant total remains 171.

The corrected seed dry-run test now expects 1,645 fragrances and 1,496 products without variants. Unique product IDs: true; unique variant IDs: true; orphan variants: 0.


## Armaf official US all-fragrances pages 1–4 — identity reconciliation (2026-11-07)

Reviewed the first four pages of the official US ARMAF `/collections/all-perfumes` listing. The live collection reports 464 listings overall, but it mixes fragrance products, body-care formats and sets; the 464 total is not a canonical perfume count.

Across pages 1–4, **47 fragrance product cards** were reviewed, representing **46 distinct fragrance display names**. All 46 distinct names resolve to existing Armaf canonical identities by exact canonical name or an existing verified alias. One additional listing, **Miss Armaf Parfum Discovery Set**, is a set and was correctly excluded from canonical fragrance identities. The title **Club de Nuit Intense Man** appears twice in the listing as separate Eau de Parfum and Eau de Toilette product pages; the catalog currently retains one canonical fragrance identity and has not yet modeled concentration-specific offers/variants for both presentations. The EDP product page is now the primary source on the existing identity; the EDT detail page is recorded as a reconciliation item for the product-variant model. No new product identities or variants were created in this pass.

Four existing identities received stronger product-level evidence instead of generic collection URLs:
- Club de Nuit Woman Extrait → https://armaf.com/products/cdn-club-de-nuit-extrait-de-parfum-spr
- Odyssey Pink Pop → https://armaf.com/products/odyssey-pink-pop-edp
- Spartacus → https://armaf.com/products/spartacus-edp
- Club de Nuit Intense Man (EDP) → https://armaf.com/products/club-de-nuit-intense-for-man

Separate EDT page for the same displayed fragrance name: https://armaf.com/products/club-de-nuit-intense-man-4. Keep the EDP/EDT distinction explicit when the product-variant schema is extended.

The official product pages confirm the first is an Extrait de Parfum, the second is an Eau de Parfum, and the third is an Eau de Parfum. The existing canonical names and IDs are retained; the longer display spellings remain covered by aliases where applicable.

Sources:
- Official all-fragrances listing, pages 1–4: https://armaf.com/collections/all-perfumes ; https://armaf.com/collections/all-perfumes?page=2 ; https://armaf.com/collections/all-perfumes?page=3 ; https://armaf.com/collections/all-perfumes?page=4
- Product detail pages linked above.

This is a **four-page reconciliation only**, not a claim that all 464 listings or all ARMAF fragrances have been reconciled. The official page's own concentration filters include body-care products and multiple sizes, so pagination and product-type classification must continue before claiming complete coverage.


### Armaf evidence-field correction

The collection classification is stored in `collection_source_url` so that the pre-existing product-detail `source_url` and `source_evidence_url` remain intact wherever they already existed. This preserves direct product evidence and prevents a collection listing from replacing a more specific product page. The Armaf regression test checks the dedicated collection-source field while existing product-detail URL tests continue to validate the direct URLs.


## Reconciliation status — current decision (2026-11-07)

**Authoritative branch snapshot:** 1,645 canonical identities, 171 explicit variants, 21 brand labels. This supersedes all earlier snapshots in this file (including 1,503, 1,572, 1,647 and other interim counts); prior sections remain as historical work notes and must not be used as the current totals.

All 20 requested brand/line labels are present. Presence is not completeness. Current top-level per-brand counts and status:
- Velixir 28 — partial; needs full current collection pagination and identity reconciliation.
- Mykonos 72 — partial; verify the requested perfume house/line only and exclude unrelated uses of “Mykonos”.
- Maison Asrar 121 — partial; fragrance-only name-level audit remains.
- Khadlaj 113 — partial; official categories mix sprays, perfume oils, home fragrance, bakhoor and sets; five final listing items and product-level evidence gaps remain.
- Bujairami 40 — partial; distributor/brand listing reconciliation remains.
- Paris Corner 129 — partial; full pagination and exact parent/sub-label assignment remain.
- Assaf 115 — partial; check current product pages, aliases and discontinued items.
- Al Wataniah 22 — partial; current official product range and formats need pagination/reconciliation.
- Armaf 303 — partial; official listings mix distinct perfumes, concentrations, multiple presentations, sets and body-care products.
- French Avenue 26 — partial; current product catalogue reconciliation remains.
- Arabiyat Prestige 32 — partial; current product catalogue reconciliation remains.
- Gulf Orchid 19 — partial; current product catalogue reconciliation remains.
- Swiss Arabian 53 — partial; reconcile regional catalogues and product-vs-home/incense formats.
- Games of Spades 4 — partial; confirm whether these are all current fragrance identities and variants.
- Lattafa 138 — partial; official perfume listing pagination and product-level matching remain.
- Afnan 71 — partial; full fragrance range reconciliation remains; separate perfume oils and sets from identity count.
- Aromatix 12 — partial; keep collaboration line distinct from French Avenue's general range.
- Maison Alhambra 237 — partial; sources include specialist distributor pages and do not prove complete manufacturer-wide coverage.
- Zimaya 71 — partial; full current product listing reconciliation remains.
- Al Haramain 37 — partial; current fragrance range and concentration/variant reconciliation remain.

### Required before declaring a brand complete
1. Capture all pages/products from an authoritative brand source or clearly identified authorized distributor, with retrieval timestamp and stable product URL.
2. Classify each listing: standalone fragrance, concentration/size variant, tester/refill, gift set/sample, perfume oil, home fragrance, body care, discontinued or ambiguous.
3. Match all products by exact product evidence, GTIN/SKU where available, and normalized brand/name; publish a missing/matched/ambiguous/excluded report.
4. Use product-detail URLs for verified products; collection URLs must remain explicitly listing-level evidence.
5. Preserve unknown size, concentration and GTIN as null. Never invent a value to fill a schema.
6. Run the full catalog, seed, and application test suites on the final branch head.

### Current CI evidence
GitHub Actions run #42417983773 on the current PR head completed successfully. The `schema-contract` job and the schema/seed integration test step passed. This is code/data validation, not proof of exhaustive commercial coverage and not a live retailer-ingestion test.

### Production and offer boundary
This catalog expansion contains product identity candidates and explicit variants only. It must not create retailer offers, prices, stock, shipping costs, commission data, or manually inserted values. The later Liquid Brun acceptance test must independently collect actual accessible retailer data, persist provenance and timestamps, and prove that ScentHunter search retrieves those worker-ingested offers.\n

## Follow-up source check — current official catalogue snapshots (2026-11-07)

This follow-up checks the official storefront collection indexes again. These totals are listing counts, not canonical perfume identity counts, and must not be copied directly into the catalog as product records.

### Paris Corner
- Official all-products page currently exposes **252 products** in the crawled snapshot: https://www.pariscornerperfumes.com/collections/all
- Its navigation explicitly separates Ministry of Oud, Paris Corner, North Stag, Pendora, Emir and Magic Oud Series. These must remain distinguishable as labels/collections rather than flattened into unrelated brand names.
- The catalog's current **129 Paris Corner parent-brand records** therefore cannot be considered complete from the storefront total alone. It needs a full listing export and classification pass, including sub-brand membership, duplicate display names, sizes/variants, gift sets and non-perfume products.
- The official collection index also exposes the relevant series navigation: https://www.pariscornerperfumes.com/collections

### Khadlaj
- The official collections index currently reports **303 All Products**: https://khadlaj-perfumes.com/collections
- The same index separately lists perfume spray, perfume oils, bakhoor, air fresheners, home/ambiance and gift-set groupings. This confirms that the 303 count is a mixed-product count and cannot be used as the expected number of perfumes.
- A dedicated official premium-range page exposes **20 products**, including named perfume sprays and sizes: https://khadlaj-perfumes.com/collections/khadlaj-premium-range/perfume-spray
- The official perfume spray collection reports **88 products**: https://khadlaj-perfumes.com/collections/khadlaj-perfume-spray
- Next action: enumerate perfume spray and EDP/extrait collections separately, then reconcile names and sizes against the 113 Khadlaj identities already in the catalog. Exclude home fragrance, bakhoor, air freshener and gift sets from standalone perfume identities unless a distinct product type is intentionally modeled.

### Maison Asrar
- The official all-products page currently reports **129 products**: https://maisonasrar.com/collections/all
- The site navigation explicitly separates **Fragrances**, **Room Spray** and **Home Fragrances**. Therefore the 129 all-products total is mixed and cannot be treated as 129 standalone perfumes.
- The current catalog has 121 Maison Asrar identities, but a product-name reconciliation against the fragrance-only collection is still required. Do not add the eight-record numerical difference as eight presumed missing perfumes.
- Official collections index: https://maisonasrar.com/collections

### ARMAF
- The official All Fragrances page currently reports **464 listings** and includes filters for Eau de Parfum, Eau de Toilette, Extrait/Parfum, body mist, body spray, deodorants, roll-ons, shampoo, shower gel and soap: https://armaf.com/collections/all-perfumes
- This confirms again that 464 is not a unique perfume identity count. Continue the existing fragrance-only product-detail reconciliation; preserve concentration differences as variants and exclude body care and sets from the perfume identity total.

### Interpretation and next action
These fresh snapshots strengthen the need for a product-type-aware reconciliation rather than raw count matching. The next implementation pass should extract listing titles and detail URLs page by page for one official source at a time, compare normalized names with the seed, and emit explicit matched/missing/ambiguous/excluded results. No missing products are inferred solely from count differences, and no retailer offers/prices/stock/shipping data are added by this catalog task.


## Pass 7 — Khadlaj and Paris Corner name-level gap sample (2026-11-07)

### Khadlaj: independent fragrance-index cross-check

Compared a sample of fragrance names shown by Fragrantica's Khadlaj Perfumes index with the current 113 Khadlaj identities. The index reports 147 fragrances and lists multiple collection families; it is a secondary reference, not a manufacturer master catalogue. The following exact displayed names were not found as exact canonical names in the current seed during this sample: **Bleu Glace, Code Viola Nectar, Gaith, Johayna Green, Maya, Musk Ice, Opulence Bleu, Qarar, Sueño, Uno Sensuale, Vanilla Kiss, Wow Oud and Zayaan Silver**.

Other sampled names, including Caffe Latte, Cashmere Sunshine Musk, Icon, Ihthiraam, Kayaan Gold, Magnate Noble, Mansion, Mocha Latte, Muse, Ombre Notes, Ria, Sara, Sawaar Vanille Blanc, Titan and Zayaan Gold, already matched existing canonical names.

These 13 absent names are **review candidates only**. Before adding them, verify each against an official Khadlaj product-detail page or official perfume-spray collection entry, then capture SKU, concentration and size only if the source actually provides them. Do not import perfume oils or home/ambience products into the spray-fragrance scope by name alone.

Secondary cross-check: https://www.fragrantica.com/designers/Khadlaj-Perfumes.html
Official collection sources for subsequent verification:
- https://khadlaj-perfumes.com/collections/khadlaj-perfume-spray
- https://khadlaj-perfumes.com/collections/khadlaj-premium-range/perfume-spray

### Paris Corner: independent fragrance-index cross-check

A current specialist index lists 261 Paris Corner fragrances, while the official all-products storefront includes multiple product lines and product types. The specialist index is useful for finding possible omissions, but it is not authoritative for current manufacturer availability or parent/sub-label attribution.

The visible index includes names such as **Rifaaqat Ume, Arwa, Atomise Intensive Men, Bayn Al Asrar, Camaro Homme Intense, Camp Fire, Cedrat Essence, Charuto Mysterious Tobacco, Charuto Regal Reserve, Cosmopolitan Newyork, December Vanilla, Dusky Vanilla, Ecstatic Blanc Fleur, Elania Emir, Fig Fete, Frenetic Delicieuse, Harrier Absolute, Hidden Halo, Honeyed Fantasy, Khair Peach Delulu, Mango Flames, Mawj Cognac Blaze, Nouf, Poppy Pulse, Taskeen Lactéa Divina and Zodiac Lunaris**.

The current seed already contains some names from this sample (for example Arwa, Bayn Al Asrar, Atomise Intensive Men, Camp Fire, Cedrat Essence and Charuto Mysterious Tobacco). This pass did not add records from the secondary index because exact matching must also account for aliases, sub-label ownership, discontinued products and possible display-name differences. Use it to generate a candidate comparison list, then resolve each candidate against the official Paris Corner product page and correct collection line.

Sources:
- Secondary cross-check: https://scentradar.eu/brands/paris-corner/
- Official all-products listing: https://www.pariscornerperfumes.com/collections/all

### Pass 7 decision

- New product identities added: **0**. This is intentional: a secondary index mismatch is not sufficient evidence to create a canonical product record.
- Khadlaj: 13 sample names flagged for official product-page verification.
- Paris Corner: secondary index used to identify candidate gaps; no speculative records added.
- No sizes, concentrations, GTINs, retailer offers, prices, stock or shipping values were inferred.
- The 1,645-product / 171-variant catalog snapshot remains unchanged by this audit pass.


## Pass 8 — Khadlaj official product-detail verification (2026-11-07)

Added six Khadlaj fragrance identities after confirming each on an official Khadlaj product-detail page:
- **Bleu Glace** — 100 ml, Extrait de Parfum; official product page: https://khadlaj-perfumes.com/ar/collections/for-him/products/bleu-glace-100-ml-extrait-de-parfum-for-men-fresh-fragrance-online-dubai-uae
- **Gaith** — 100 ml, Eau de Parfum; official product page: https://khadlaj-perfumes.com/collections/all/products/gaith-100-ml-edp-spray-men-perfumes-dubai-uae
- **Qarar** — 60 ml, Extrait de Parfum; official product page: https://khadlaj-perfumes.com/products/khadlaj-qarar-unisex-bold-oriental-extrait-de-parfum
- **Sueño** — 100 ml, Extrait de Parfum; official product page: https://khadlaj-perfumes.com/collections/best-selling-perfumes/products/sueno-100ml-extrait-de-parfum-for-women
- **Wow Oud** — 100 ml, Eau de Parfum; official product page: https://khadlaj-perfumes.com/collections/oud-range/products/wow-oud-100-ml-edp-spray
- **Zayaan Silver** — 100 ml, Eau de Parfum; official product page: https://khadlaj-perfumes.com/products/zayaan-silver-fresh-aquatic-spicy-woody-eau-de-parfum-for-men

Each identity has one explicit variant with the source-confirmed size and concentration. GTINs are retained only where the official product detail page exposed one; Bleu Glace GTIN remains null/absent because the checked page did not establish it. No price, stock or retailer offer was imported.

The following candidates remain **not added**: Code Viola Nectar (currently only corroborated by a third-party retailer in this pass), Johayna Green (official listing places it under perfume oils, outside the spray-fragrance identity pass), Maya (official listing shows a 20 ml item but its product type/format needs a product-detail check), Musk Ice (already represented as Private Blend Musk Ice), and Uno Sensuale / Vanilla Kiss / Opulence Bleu (not yet verified from an official Khadlaj product-detail page during this pass).

### Pass 8 result
- New canonical identities: **6**.
- New explicit variants: **6**.
- Khadlaj branch count: **119** (previously 113).
- Catalog snapshot: **1,651 canonical identities; 177 explicit variants**.
- These additions are product identity/variant records only. They are not retailer offers and do not imply current purchasable stock.
- A dedicated regression test was added for all six official product URLs, sizes, concentrations and variant links. CI for the resulting commit has not yet been observed; do not describe this pass as CI-verified until Actions completes.

## Pass 9 — Paris Corner official sub-line reconciliation (2026-11-07)

Reconciled additional entries against the current official Paris Corner collection pages. Added **28 source-listed fragrance identities** with explicit parent-brand and collection attribution:

- **Magic Oud Series — 4:** Magic Oud Dark Roses, Magic Oud In Pure Zaffron, Magic Oud Kalimath, Magic Oud Kashmir Musk. The existing Magic Oud Sandal Wood identity was retained.
- **North Stag — 8:** Quatre IV Expressions, Trois III Expressions, Deux II Expressions, Un I Expressions, Hypnotic Oud Quinze XV, Phenomenal Quatorze XIV, Huit VIII and Sept VII. The existing Neuf IX identity was retained. The North Stag Set of Three was excluded as a set.
- **Ministry of Oud — 12:** Amber Oud, Oud Indonesian, Oud Royal, Oud Satin, Strictly Oud, Thailand Oud in Cairo, Greatest, Gladiators Oath, Maestro's Symphony, Nile Whispers, Oud Beyond the Wall and Romance Reverie. The Ministry of Oud 50 ml Signature Set was excluded as a set.
- **Ministry of Gourmand — 4:** Creamy Biscuit, Mango Jugoso, Strawberry Pound Cake and Tiramisu Speculoos.

All 28 records use the official collection page as listing-level evidence and retain identity_status=source_listed_name. Size, concentration, GTIN and variants were deliberately left unset because the collection listings did not establish those product-level facts. No product-detail URL, offer, price, stock or shipping data was invented.

Official sources:
- Magic Oud Series: https://www.pariscornerperfumes.com/collections/magic-oud-series
- North Stag: https://www.pariscornerperfumes.com/collections/north-stag-1
- Ministry of Oud: https://www.pariscornerperfumes.com/collections/ministry-of-oud
- Ministry of Gourmand: https://www.pariscornerperfumes.com/collections/ministry-of-gourmand

Regression coverage was added for all 28 names, their official collection membership and source URLs, and the deliberate absence of unsupported size/concentration data.

### Pass 9 result
- New canonical identities: **28**.
- New variants: **0**.
- Paris Corner branch count: **157** (previously 129).
- Catalog snapshot: **1,679 canonical identities; 177 explicit variants**.
- Product IDs and variant IDs remain unique; orphan variants: **0**.
- This is a partial line-level reconciliation, not a claim that all Paris Corner products are complete. Pendora Scents, Emir and the parent Paris Corner collection still require full page-by-page reconciliation, including product detail verification and classification of sets/other formats.
- The new regression test is committed; CI has not yet been observed for the updated branch head.

## Pass 10 — Paris Corner Emir and Pendora Scents reconciliation (2026-11-07)

Compared the current official collection listings with the existing Paris Corner identities and aliases. Added **70 source-listed fragrance identities**:

- **Emir — 44 new identities.** The official Emir collection reports 54 products; 10 identities were already represented in the catalog and the remaining 44 visible names have now been added. Names include Cosmopolitan Newyork, Elania Emir, Fascination Emir, Fire Your Desire Emir, the Lueur d'Espoir and Opulentia entries, Voux variations, Valar Series entries and others shown in the official collection.
- **Pendora Scents — 26 new identities.** Names added include Doris Pink, Dusky Vanilla, Ecstatic Blanc Fleur, English Leather, Enormity, Fig Fete, Hidden Halo, Honeyed Fantasy, Intense Wayfarer, Intima Red, La Nuit Pendora, Lullaby, Mango Flames, Nectarine Haze, Neon Star, Noir d'Arabie, Oud Holidays, Poppy Pulse, Praise, Precision, Rose de Nuit, The Aoud, The Green, The Peace, The Scent and The Street. The official collection reports 36 products, while the currently exposed listing text identifies 32 names including six already represented. Four entries still need a complete listing extraction before this collection can be called reconciled.
- **Parent Paris Corner:** no additional parent-line identity was imported in this pass. A name visible in the mixed all-products feed was deliberately not assigned to the parent line without evidence from the dedicated parent collection.

Official listing evidence:
- Emir collection (54 products): https://www.pariscornerperfumes.com/collections/emir-1
- Emir page 2 listing: https://www.pariscornerperfumes.com/collections/emir-1?page=2
- Pendora Scents collection (36 products): https://www.pariscornerperfumes.com/collections/pendora-scents-1
- Paris Corner parent collection: https://www.pariscornerperfumes.com/collections/paris-corner

All 70 new rows remain source_listed_name records backed by collection pages. No unsupported product-detail URLs, sizes, concentrations, GTINs or variants were added. No retailer offers, prices, stock or shipping data were created.

A regression test asserts all 70 names, parent brand, exact collection attribution, source URLs and the absence of unsupported size/concentration data.

### Pass 10 result
- New canonical identities: **70**.
- New variants: **0**.
- Paris Corner branch count: **227** (previously 157).
- Catalog snapshot: **1,749 canonical identities; 177 explicit variants**.
- Emir collection: 54/54 names accounted for in the current source snapshot (10 existing + 44 new).
- Pendora Scents: 32 of 36 listing names currently identified (6 existing + 26 new); four remaining listing entries require another extraction pass.
- The parent Paris Corner collection and the entire 252-item all-products feed still require complete pagination and classification. This is not an exhaustive Paris Corner completion claim.
- The new regression test is committed; CI status for the latest branch head must be checked before describing it as passed.

## Pass 11 — Pendora Veteran Oud and complete Paris Corner parent collection (2026-11-07)

A deeper check of the dedicated Pendora gender collections found one additional official product not present in the main Pendora Scents listing text: **Veteran Oud**, shown in the official Pendora Scents - Men collection. Added it as a Paris Corner / Pendora Scents source-listed identity. The main Pendora collection reports 36 products but its currently rendered listing text exposes 32 named cards; the men collection exposes four cards (Veteran Oud, English Leather, Charuto Mysterious Tobacco and Rose de Nuit), and the women collection exposes three cards (La Nuit Pendora, Charuto Mysterious Tobacco and Rose de Nuit). All but Veteran Oud were already represented. The discrepancy between the main collection's 36-product counter and 32 visible names remains unresolved; no speculative products were added.

The dedicated Paris Corner parent collection was also reconciled across all four pages. The current official collection reports **105 products**, and the catalog already contains the exact 105-name set:
- Page 1: 32 identities.
- Page 2: 32 identities.
- Page 3: 32 identities.
- Page 4: 9 identities.

A regression test now asserts the complete 105-name set and exact page-level source counts. No parent-line products needed to be added in this pass.

Official sources:
- Pendora Scents - Men: https://www.pariscornerperfumes.com/collections/pendora-scents-men
- Pendora Scents - Women: https://www.pariscornerperfumes.com/collections/pendora-scents-women
- Paris Corner parent collection page 1: https://www.pariscornerperfumes.com/collections/paris-corner
- Paris Corner parent collection page 2: https://www.pariscornerperfumes.com/collections/paris-corner?page=2
- Paris Corner parent collection page 3: https://www.pariscornerperfumes.com/collections/paris-corner?page=3
- Paris Corner parent collection page 4: https://www.pariscornerperfumes.com/collections/paris-corner?page=4

### Pass 11 result
- New canonical identities: **1** (Veteran Oud).
- New variants: **0**.
- Paris Corner branch count: **228** (previously 227).
- Catalog snapshot: **1,750 canonical identities; 177 explicit variants**.
- Parent Paris Corner collection: **105/105** current official listing names reconciled over four pages.
- Pendora Scents: Veteran Oud added from the official men collection. Main collection's visible-name/count discrepancy remains open and is not represented as complete.
- New tests cover Veteran Oud source attribution and all 105 parent collection identities.
- CI for the latest catalog/test/docs commits must be checked before describing these tests as passed.

## Pass 12 — Paris Corner official product-detail verification (2026-11-07)

The official 252-item all-products feed exposed additional fragrances not represented in the previous catalog snapshot. Verified 16 of these directly on official Paris Corner product-detail pages and added each with one source-confirmed size variant:

| Identity | Size | Official detail page |
|---|---:|---|
| Frenetic Men | 100 ml | https://www.pariscornerperfumes.com/products/frenetic-men |
| Frenetic Red Tempt | 80 ml | https://www.pariscornerperfumes.com/products/frenetic-red-tempt |
| Frenetic Tobacco Honey | 100 ml | https://www.pariscornerperfumes.com/products/frenetic-tobacco-honey |
| Identity Oud Crescent | 100 ml | https://www.pariscornerperfumes.com/products/identity-oud-crescent |
| Identity Rose & Leather | 100 ml | https://www.pariscornerperfumes.com/products/identity-rose-leather |
| Identity Unique Portrait | 100 ml | https://www.pariscornerperfumes.com/products/identity-unique-portrait |
| Intense Oud | 100 ml | https://www.pariscornerperfumes.com/products/intense-oud-arabian |
| Intense Oud Saffron | 100 ml | https://www.pariscornerperfumes.com/products/intense-oud-saffron |
| Le Charme | 100 ml | https://www.pariscornerperfumes.com/products/la-charme-emir |
| Protocol Edition | 100 ml | https://www.pariscornerperfumes.com/products/protocol-edition |
| Resurrection | 100 ml | https://www.pariscornerperfumes.com/products/resurrection |
| The Triumphant Sapphire | 100 ml | https://www.pariscornerperfumes.com/products/the-triumphant-sapphire |
| Toxic Heart | 100 ml | https://www.pariscornerperfumes.com/products/toxic-heart |
| You're Drugged Emir | 100 ml | https://www.pariscornerperfumes.com/products/youre-drugged-emir |
| Frenetic Delicieuse | 80 ml | https://www.pariscornerperfumes.com/products/frenetic-delicieuse |
| Frenetic Homme Intense | 80 ml | https://www.pariscornerperfumes.com/products/frenetichomme-intense |

Collection attribution is limited to evidence available on the official page: Frenetic Tobacco Honey, Le Charme, Resurrection and You're Drugged Emir are assigned to Emir; Protocol Edition is assigned to Pendora Scents; the remaining items are attributed to the Paris Corner parent collection. The source detail pages establish the listed sizes. Concentration and GTIN remain unset where the pages did not establish them. No commercial offers, prices or stock were created.

A regression test checks all 16 product-detail URLs, line attribution, sizes and variant relationships.

### Pass 12 result
- New canonical identities: **16**.
- New explicit variants: **16**.
- Paris Corner branch count: **244** (previously 228).
- Catalog snapshot: **1,766 canonical identities; 193 explicit variants**.
- These are product identity/variant records only; they do not establish current retailer availability.
- The official all-products feed still needs a full name-by-name reconciliation. The 252 feed count includes product types and lines that require classification; not every listing should become a standalone perfume identity.
- CI for the latest branch head must complete before treating the new regression test as passed.

## Pass 13 — catalog attribution and CI regression correction (2026-11-07)

The first Actions runs exposed stale hard-coded catalog counts and an attribution issue in the new detail-page additions. The catalog and tests have been corrected:

- Updated seed assertions to the current **1,766 identities / 193 variants / 1,573 products without variants**.
- Preserved the Paris Corner parent collection as exactly **105 identities**. Eleven additional product-detail identities whose exact sub-line is not established are now labeled Unclassified, rather than incorrectly counted as members of the parent collection.
- Added source_product_url and corrected source_evidence_url for six previously cataloged 100 ml Paris Corner products (Confidential, Khayal, Minya, Ophidian Black Cherry, Qawafi and Taskeen Lactea Divina).
- Kept the 16 newly verified product-detail identities and their size variants; line attribution remains explicit only where the official page supports it.

The failed runs reported 32–33 passing tests and failures from the stale totals, old detail evidence, and the over-broad parent-collection count. The corrections are committed, but no successful Actions run for the corrected current head has yet been observed. Do not mark CI green until a fresh run completes.

## Pass 14 — corrected catalog checks green (2026-11-07)

The corrected branch head was checked by GitHub Actions run **#42419260784**. The Phase 2 schema-contract job completed successfully and the test command reported **37 passed, 1 warning**. This run includes the current catalog count assertions, product-detail provenance checks, Paris Corner parent collection exact-name test, Pendora Veteran Oud test and the 16 new product-detail/variant assertions.

The earlier failures were from superseded commits. The latest verified head is **1f5dcb4766bb300a327fa57d196b522c4ed3e7a8**. The warning is from the existing dependency/tooling deprecation output; it did not fail the test job.

## Pass 15 — additional Paris Corner detail-page identities (2026-11-07)

Continued reconciling the official all-products feed and added six more fragrances only after checking their official product-detail pages:

- **Harrier Absoulte** — 100 ml; official page retains the displayed spelling “Absoulte”.
- **Wild and Tobacco Emir** — 75 ml; assigned to Emir based on its official product name.
- **Lueur d'Espoir Noche** — 100 ml.
- **Lueur d'Espoir Arena** — 100 ml.
- **Lueur d'Espoir Ambre** — 100 ml.
- **Wayfarer Eau de Parfum** — 100 ml; kept separate from Intense Wayfarer because the official names and detail pages are distinct.

Official detail pages:
- https://www.pariscornerperfumes.com/products/harrier-absoulte
- https://www.pariscornerperfumes.com/products/wild-and-tobacco-emir
- https://www.pariscornerperfumes.com/products/lueur-noche
- https://www.pariscornerperfumes.com/products/lueur-arena
- https://www.pariscornerperfumes.com/products/lueur-ambre
- https://www.pariscornerperfumes.com/products/wayfarer-dau-de-parfum

The three Lueur d'Espoir entries, Harrier Absoulte and Wayfarer are kept as Unclassified because the checked product pages establish Paris Corner product identity and size but do not unambiguously establish membership in one of the sub-lines modeled here. No concentration or GTIN was inferred.

A regression test checks the six official product URLs, sizes, collection classification and explicit variant relationships.

### Pass 15 result
- New canonical identities: **6**.
- New explicit variants: **6**.
- Paris Corner branch count: **250** (previously 244).
- Catalog snapshot: **1,772 canonical identities; 199 explicit variants**.
- The parent Paris Corner collection remains exactly 105/105. Unclassified products from the mixed all-products feed are not incorrectly counted as parent-collection members.
- CI for these latest additions must be checked against the current branch head.

## Pass 16 — latest Paris Corner regression suite green (2026-11-07)

The latest test commit **8b51c6fb8f9fa36136718edd39d0faa6fe64a655** completed GitHub Actions run **#42419385171** successfully. The Phase 2 schema-contract job reports **38 passed, 1 warning**. This run includes the six additional detail-page identities and variants, updated totals, the 105-item parent collection regression, and prior Paris Corner line/detail checks.

The immediately preceding run (#42419374203) failed only because it tested the catalog commit before the count assertions were updated. The later run against the test commit is green.

## Pass 17 — three further official Paris Corner detail pages (2026-11-07)

Added three more fragrances from the official all-products feed after direct product-detail verification:

- **Empire de la Rouge** — 100 ml: https://www.pariscornerperfumes.com/products/empire-de-la-rouge
- **Vivant Sunlit** — 100 ml: https://www.pariscornerperfumes.com/products/vivant-sunlit
- **Wayfarer Infusion** — 100 ml: https://www.pariscornerperfumes.com/products/wayfarer-infusion

All three have one explicit 100 ml variant. They remain Unclassified because the checked detail pages establish the product identity and size but not membership in the modeled Emir, Pendora Scents, North Stag, Ministry of Oud or Magic Oud lines. Wayfarer Infusion is kept distinct from Wayfarer Eau de Parfum and Intense Wayfarer.

### Pass 17 result
- New canonical identities: **3**.
- New explicit variants: **3**.
- Paris Corner branch count: **253** (previously 250).
- Catalog snapshot: **1,775 canonical identities; 202 explicit variants**.
- New regression coverage asserts the official detail URLs, sizes and variant relationships.
- CI for the latest addition is pending.

## Pass 18 — latest CI verification green (2026-11-07)

GitHub Actions run **#42419497636** for test commit **1a2f65636640f3cda0a0695f2a14ad225b78635e** completed its Phase 2 schema-contract test command successfully: **39 passed, 1 warning**. This includes the three latest Paris Corner detail-page products (Empire de la Rouge, Vivant Sunlit and Wayfarer Infusion) and their explicit 100 ml variants.

## Pass 19 — Khadlaj La Fede and concentrated perfume oil verification (2026-11-07)

Added three Khadlaj-house identities after confirming official product-detail pages:

- **Code Viola Nectar** — 100 ml EDP spray; the official product page identifies it as La Fede and exposes the 100 ml size. Its description uses the variant spelling “Necter”; canonical name follows the page heading.
- **Uno Sensuale** — 100 ml EDP spray; official Uno Range / La Fede product page.
- **Maya** — 20 ml concentrated perfume oil; official product page explicitly classifies it under concentrated perfume oils, not spray perfume.

Official sources:
- Code Viola Nectar: https://khadlaj-perfumes.com/products/code-viola-nectar-spray-shop-online-best-price-in-dubai-uae
- Uno Sensuale: https://khadlaj-perfumes.com/collections/women-perfume/products/uno-sensuale-edp-spray-shop-online-best-price-in-dubai-uae
- Maya: https://khadlaj-perfumes.com/products/khadlaj-maya-20-ml-alcohol-free-perfume-attars-online-dubai-uae

The source collection is recorded separately from the product-detail evidence. Maya is modeled under Concentrated Perfume Oils so it is not confused with a spray. No GTIN was inferred from the displayed SKU fields.

### Pass 19 result
- New canonical identities: **3**.
- New explicit variants: **3**.
- Khadlaj branch count: **122** (previously 119).
- Catalog snapshot: **1,778 canonical identities; 205 explicit variants**.
- A regression test checks product-detail URLs, source collection URLs, sizes, line attribution and variant links.
- CI for this pass must complete before marking it verified.

## Pass 20 — Khadlaj verification tests green (2026-11-07)

GitHub Actions run **#42419642110** for test commit **64729d87823a409019b97d3d12d0edc9fc921a4a** completed successfully. The Phase 2 schema-contract suite reports **40 passed, 1 warning**, including the new Code Viola Nectar, Uno Sensuale and Maya product-detail/variant assertions.

## Pass 21 — remaining official Khadlaj Uno Range products (2026-11-07)

The official Khadlaj Uno Range collection contains four perfume sprays, all 100 ml. Uno Sensuale was already added in Pass 19. Added the other three after checking their official detail pages:

- **Uno Lusso** — 100 ml Eau de Parfum: https://khadlaj-perfumes.com/collections/all/products/uno-lusso-edp-spray-shop-online-best-price-in-dubai-uae
- **Uno Intimo** — 100 ml Eau de Parfum: https://khadlaj-perfumes.com/collections/uno-range/products/uno-intimo-edp-spray-shop-online-best-price-in-dubai-uae
- **Uno Durable** — 100 ml Eau de Parfum: https://khadlaj-perfumes.com/collections/best-selling-perfumes/products/uno-durable-edp-spray-shop-online-best-price-in-dubai-uae

All three are assigned to the Uno Range within the Khadlaj house, with one explicit 100 ml EDP variant each. The official collection page reports four products in this range; all four are now represented in the catalog.

### Pass 21 result
- New canonical identities: **3**.
- New explicit variants: **3**.
- Khadlaj branch count: **125** (previously 122).
- Catalog snapshot: **1,781 canonical identities; 208 explicit variants**.
- Regression coverage checks the three product-detail URLs, source collection, 100 ml size and Eau de Parfum concentration.
- CI for this pass must complete before marking it verified.

## Pass 22 — Khadlaj Uno Range CI green (2026-11-07)

GitHub Actions run **#42419757178** for test commit **f8f4fa359956e4dc9f9fd71433d610f6ae9cb3a5** passed the Phase 2 schema-contract suite: **41 passed, 1 warning**. The run includes the three added Uno Range product-detail records and their 100 ml Eau de Parfum variants.

## Pass 23 — La Fede Eau De Parfum collection reconciliation (2026-11-07)

Reconciled the official **La Fede Eau De Parfum** collection, which currently reports 42 perfume-spray products. Five of those identities were already represented in the catalog (Code Viola Nectar and the four Uno Range products). Added the remaining **37 identities** from the official collection listing, preserving the displayed names, size and concentration:

- 100 ml Extrait de Parfum: La Fede Intoxicate Mystique.
- 100 ml Eau de Parfum: Edge Intense, Edge Original, Symbol of Love, Symbol of Power, Choco Brown, White Forest Strawberry, Celeste Toffee, Celeste Fluer, Celeste Joice, Celeste Aqua, Intoxicate Blue Elixir, Intoxicate, Aura Manga Splash, Aura Pista Dessert, Opera Noir L'Or, Opera Rose L'Or, Crystallia Imperio, Crystallia Primaso, Magnum Extreme Blue, Magnum Wild Green, Magnum Gold Edition, Magnum Silver Edition, Aura Kiss of Rose, Aura Crisp Flower, Belle Reve Segrato Viola, Bella Reve Dolce Flore, Code Marron Oud, Code Rouge Amour, Code Verde Sublime, Lavish Luna, Lavish Rouge and Lavish Blush.
- 75 ml Eau de Parfum: Statesman, First Lady, Kingsman and Miss Premiere.

Official collection listing: https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume

All 37 records use collection-level evidence and retain the status source_listed_name. Size and concentration are copied only where shown in the official collection card title. No product-specific URL or GTIN was invented. Existing Code Viola and Uno records remain distinct and are not duplicated.

### Pass 23 result
- New canonical identities: **37**.
- New explicit variants: **37**.
- Khadlaj branch count: **162** (previously 125).
- Catalog snapshot: **1,818 canonical identities; 245 explicit variants**.
- La Fede Eau De Parfum collection: **42/42 listing identities accounted for** (37 new + 5 existing).
- Regression coverage checks all 37 names, official collection evidence, sizes, concentrations and variant links.
- CI for the latest additions must complete before marking them verified.

## Pass 24 — La Fede collection regression suite green (2026-11-07)

GitHub Actions run **#42419917309** for test commit **79f250e828172ad357ca50f678ba9ff2e9d72a47** completed successfully. The Phase 2 schema-contract suite reports **42 passed, 1 warning**, including all 37 La Fede collection identities and their explicit size/concentration variants.

## Pass 25 — Maison Asrar perfume-spray collection reconciliation (2026-11-07)

Compared the official Maison Asrar perfume-spray collection across its paginated listings. The current collection counter is 73–74 depending on the crawl snapshot; the visible product names reconcile to **74 distinct listing identities**. All 74 map to the existing Maison Asrar catalog, with one naming difference: the collection card displays **Mohra Oud**, while the official product-detail page canonical heading is **Mohra**. Added “Mohra Oud” as an alias to the existing Mohra identity and recorded its official product-detail URL rather than creating a duplicate product.

Official sources:
- Perfume sprays: https://maisonasrar.com/collections/perfume-sprays
- Paginated collection: https://maisonasrar.com/collections/perfume-sprays?page=2 through page 7
- Mohra detail page: https://maisonasrar.com/products/mohrab
- Room sprays are separately listed in an eight-item collection: https://maisonasrar.com/collections/room-spray

The Maison Asrar catalog remains at **121 canonical identities**. The eight room-spray SKUs are not added as perfume identities. The official all-products collection lists 129 products; its product and room-spray categories must remain distinct.

A regression test now asserts the 74 official perfume-spray names map to the 121 existing Maison Asrar identities, verifies the Mohra Oud alias, and ensures room-spray titles are not imported as perfume identities.

### Pass 25 result
- New canonical identities: **0** (no duplicates created).
- New aliases: **1** (Mohra Oud → Mohra).
- Maison Asrar branch count: **121**.
- Catalog snapshot: **1,818 canonical identities; 245 explicit variants**.
- CI for this new reconciliation test must complete before marking it verified.

## Pass 26 — Maison Asrar full spray-list test green (2026-11-07)

GitHub Actions run **#42420311483** for test commit **f2a76caf021ddbee36db6c4c24635b3a8eef83ba** passed: **43 tests passed, 1 warning**. This includes the full 74-name Maison Asrar perfume-spray mapping, the Mohra Oud alias, and the room-spray exclusion assertion. The preceding failure was a case-normalization error in the test itself; the catalog mapping was complete and the corrected test now passes.

## Pass 27 — Al Wataniah official catalog expansion (2026-11-07)

The current official Al Wataniah all-products collection reports **123 products** and mixes perfumes with air fresheners and perfumed body mists. The branch previously contained only 22 Al Wataniah identities (10 current perfume names plus 12 announced/launching-soon names). Compared the four paginated all-products pages and added **73 missing perfume identities**; air-freshener and body-mist SKUs were not imported as perfume identities.

New names include Al Daiem, Al Daiem Elixir, Al Layl, Alya, Ameerati, Ameeri, Amnia, Anwan, Arya, Arya Peony Rose, Attar Al Wesal, Attar Al Wesal Elixir, Baraa, Bareeq Al Dhahab, Castilla, Crème, Da'im, Duha, Durrat Al Aroos, Eqaab, Emiran, Emiran Selar, Fayroz, Fayyad, Fikrah, Ghala, Golden Honey, Granada, Hala, Hayat, House Of Oud, Kenz Al Malik, Layali, Lazuli, Lily, Marjaan, Massad Royale, Muheeb, Nada, the four Nawal gemstone fragrances, Oud Mystery Intense, Praline Toffee, Qasar Al Watan, Rawaee Elite / Monarch / Noble / Regina, Redaa, Rose Mystery Intense, Royal Oak I / II, Sabah Al Ward and its variants, Sahari, Sevilla, Shagaf Al Ward and Gardenia, Special Oud, Sugar Rush, Sultan Al Lail, Thahaani, Tiara Pink, Tibyan, Watani Intense Gold / Noir / Purple, White Chocolate Ganache and Ziyana.

Official evidence is the relevant paginated product listing:
- Page 1: https://www.alwataniah.com/collections/all
- Page 2: https://www.alwataniah.com/collections/all?page=2
- Page 3: https://www.alwataniah.com/collections/all?page=3
- Page 4: https://www.alwataniah.com/collections/all?page=4

These are listing-level identity records only. Product sizes, concentrations, GTINs and variants were not inferred from the collection cards. The family registry was synchronized to include all 95 Al Wataniah identities, including the 12 previously announced products.

### Pass 27 result
- New canonical identities: **73**.
- New variants: **0**.
- Al Wataniah branch count: **95** (previously 22).
- Catalog snapshot: **1,891 canonical identities; 245 explicit variants**.
- Air fresheners and perfumed body mists remain outside the perfume identity catalog.
- A regression test checks all 73 names, page-specific source URLs, family-registry membership and missing size/concentration data.
- CI for the latest Al Wataniah test must complete before marking this pass verified.

## Pass 28 — Al Wataniah regression suite green (2026-11-07)

GitHub Actions run **#42420558957** for test commit **f0c4b4872d8faf1208f4237538982bf4da297e58** passed the Phase 2 schema-contract suite: **44 passed, 1 warning**. This includes the 73 Al Wataniah listing identities, page-level source URLs, and family-registry consistency assertions.



## Official listing reconciliation pass 7 — Velixir, Mykonos, Lattafa, Khadlaj, Paris Corner (2026-11-08)

### Velixir
- The brand's official site is https://velixirparfums.com/ .
- An independent full-range index at https://velixirperfumes.eu/perfumes/ lists 28 named fragrances (24 EDP and four Extrait), including the October 2026 additions Comus, Ether, Orpheus and Panacea. The index explicitly identifies itself as an independent reseller, not the official brand website.
- The current PR snapshot reports 28 Velixir identities. Treat this as a name-level cross-check, not proof that all current global SKUs/variants are present.
- A dated research overlay now records the 28 names and size/concentration claims as source-listed candidates; do not create variants until the individual brand product pages confirm each detail.

### Mykonos
- Official collection: https://officialmykonos.com/collections/all . It currently reports 54 products and the product list was inspected across pages 1–4:
  - https://officialmykonos.com/collections/all?page=1
  - https://officialmykonos.com/collections/all?page=2
  - https://officialmykonos.com/collections/all?page=3
  - https://officialmykonos.com/collections/all?page=4
- One listing, "Travel Size 15ML", is a presentation/size format rather than a separate fragrance identity and was excluded from the 53 named fragrance candidates. Collaboration products (MyEgo, Empire, Glitch, Invade) retain their collaboration labels.
- Independent Fragrantica index lists 84 Mykonos fragrances, which is a different scope from the current official shop's 54 products. Do not force these totals to match.
- The current PR snapshot reports 72 Mykonos canonical identities. This exceeds the 53 currently named fragrance candidates in the official shop. The discrepancy requires name-by-name reconciliation for discontinued products, new releases, aliases, collaborations, and possible non-fragrance listings; do not blindly add these candidates as new identities.
- Product title size/concentration options in the official collection are discovery evidence only. They are not yet canonical variant rows.

### Lattafa
- Official perfume category: https://lattafa.com/product-category/perfumes/ . The visible sample includes Fahad, Khamrah Waha, Sheikh Al Shuyukh Supreme, Jouri, Ana Abiyedh Passion, Ameerat Al Arab Sugar Crown, Lattafa Mishlah, Angham Second Song, Maahir Honor, Dalal, Yara Elixir and Asad Elixir.
- An official US shop index at https://www.lattafa-usa.com/collections/all reports mixed product counts and includes air fresheners, oils, deodorants and other non-perfume formats. Do not use its overall count as a perfume-only canonical count.
- The earlier audit sample found ten names already in the current catalog. This remains a spot-check, not a full pagination reconciliation.

### Khadlaj
- Official collections index: https://khadlaj-perfumes.com/collections . It reports 308 products in "All Products" but explicitly mixes perfume sprays, concentrated oils, bakhoor, air fresheners, home fragrance and gift sets.
- The "Khadlaj Perfume Spray" collection reports 88 products; it is a more relevant starting point but still requires product-level type and variant review.
- Fragrantica's current index lists additional names across lines such as Biscotti, Empire, Fursan, Hareem Al Sultan, Karus, Shiyaaka, Valor and Velvet. Treat it as a cross-check only, not official master data.
- Do not import the 308 count or every collection listing as a standalone fragrance.

### Paris Corner
- Official core-brand collection: https://www.pariscornerperfumes.com/collections/paris-corner . It currently reports 104 products (a prior dated observation showed 105). The visible page distinguishes product names; the broader collections index lists separate sub-lines including Emir, Magic Oud Series, Ministry of Gourmand, Ministry of Oud, North Stag and Pendora Scents.
- Parent brand and sub-line ownership must remain separate; do not automatically attribute every sub-line item to the core Paris Corner brand.
- Pagination and product-type reconciliation remain required.

### Artifacts
- `backend/catalog_overlays/official_brand_listing_reconciliation_2026-11-08.json` records 28 Velixir and 53 Mykonos name candidates with source links and the unresolved catalog reconciliation.
- No retailer offers, prices, stock, shipping costs, or inferred GTINs were imported.
- No production database, production configuration, or store authorization was changed.


## Pass 29 — Games of Spades official collection reconciliation (2026-11-08)

### Source and identity hierarchy
- Manufacturer: Jo Milano Paris.
- Requested fragrance line / catalog brand label: Games of Spades.
- Official collection source: https://jomilanoparis.com/collections/all?page=1 and https://jomilanoparis.com/collections/all?page=2 .
- Official individual product pages were also checked for King, Queen, Wildcard, All In, Jackpot, Rouge, Royale, Blind Bid and Gold.
- The official site separates perfume products from gift sets/coffrets. Gift sets are not added as standalone canonical fragrance identities.

### Catalog changes
- Before this pass, the canonical catalog had four Games of Spades identities: King, Queen, Ace and Wildcard.
- The family registry already included Jack, but the canonical product catalog did not. Jack was added.
- Added 26 source-listed canonical fragrance identities to `backend/product_catalog.json`: Jack, All In, Bid, Black Sapphire, Blind Bid, Bluff, Bonus, Boston, Diamond, Double Bonus, Emerald, Full House Refresh, Gold, High Roller, Jackpot, Moon, No Limit, Opal, Platinum, Rouge, Royale, Ruby, Topaz, Trick, Win and Yellow Sapphire.
- The canonical catalog now contains 30 Games of Spades fragrance identities. The family registry contains 30 matching identities.
- New product IDs use the stable `SH-GOS-<normalized-name>` form; no existing IDs were changed.
- No variants were created. Product pages show different sizes and concentration presentations for some products (for example Rouge / Rouge Extrait); these require explicit variant modeling and are not treated as separate fragrance identities in this pass.
- No GTIN, price, availability, shipping cost, retailer offer or stock was imported.

### Validation and limitations
- New identities are source-listed from the official Jo Milano Paris product collection; individual product detail evidence is attached where available.
- The 26 additions are canonical name identities, not a claim that every historic/discontinued Game of Spades release is represented.
- The new test `backend/tests/test_games_of_spades_catalog.py` asserts catalog/registry consistency, unique IDs and brand/name pairs, and that no commercial offer fields or unverified variants are added.
- GitHub Actions must pass on the latest PR head before this pass is called CI-verified.


## Pass 30 — Lattafa official product-detail gap closure (2026-11-08)

- A product-by-product comparison found two official Lattafa fragrance names present in the family registry or source discovery but missing from the canonical product seed: **Queen of Arabia** and **Musamam Black Intense**.
- Both names were confirmed on Lattafa's official product pages:
  - https://lattafa.com/product/queen-of-arabia/
  - https://lattafa.com/product/musamam-black-intense/
- Added both canonical product identities to `backend/product_catalog.json` and synchronized the Lattafa family registry. Musamam Black Intense already existed in the family registry; Queen of Arabia was added there as well.
- No variants were created. The Queen of Arabia page displays 100 ml, but no size variant row was created in this pass; Musamam Black Intense's page identifies it as Eau de Parfum without a verified size in the extracted source. No GTIN, price, stock, shipping or retailer offer was added.
- Added `backend/tests/test_lattafa_catalog.py` for official source URL, identity status, registry parity and no-offer assertions.
- Catalog totals after Games of Spades and Lattafa additions: **1,919 canonical identities; 245 explicit variants**. CI status remains pending verification on the latest PR head.


## Pass 31 — French Avenue official product-detail gap closure (2026-11-08)

- The candidate reconciliation found three French Avenue fragrance names missing from the canonical product seed: **Jasmere**, **Amber Empire** and **Safari Breeze**.
- All three are supported by French Avenue official product pages:
  - Jasmere: https://frenchavenue.com/products/jasmere
  - Amber Empire: https://frenchavenue.com/products/amber-empire
  - Safari Breeze: https://sa.frenchavenue.com/products/safari-breeze (official Saudi Arabia storefront)
- Added the three canonical identities to `backend/product_catalog.json` and synchronized `french_avenue_catalog` in the family registry.
- Jasmere and Safari Breeze pages explicitly state EDP 100 ml; this pass records the product identities only and does not create variant rows. Amber Empire is recorded by official product name only. No GTIN, price, stock, shipping or retailer offer was imported.
- Updated the dated name-harvest overlay with the official detail URLs and added `backend/tests/test_french_avenue_catalog.py` for provenance, uniqueness, registry parity and no fabricated commercial fields.
- Catalog totals after Games of Spades, Lattafa and French Avenue additions: **1,922 canonical identities; 245 explicit variants**. CI remains unverified on the latest PR head.


### Correction to Games of Spades pass 29 — Jack remains discovery-only (2026-11-08)
A final source check found that **Jack** was present in the pre-existing family registry but could not be confirmed in the current Jo Milano Paris official product listings or individual product pages reviewed for this pass. It has therefore been removed from the canonical product seed and from the official-listing harvest candidates. The registry entry is retained as a discovery-only candidate pending authoritative product evidence. The Games of Spades canonical count is **29**, not 30. The regression test now requires canonical identities to be a subset of the broader family registry, allowing unverified discovery names to remain outside the canonical seed.


## Pass 32 — Remaining candidate gate: Hectic and Mahd Al Dhahab Extrait (2026-11-08)

Two names remain in the discovery harvest but were deliberately **not** added to the canonical product seed:

### Bujairami — Hectic
- The official Bujairami web presence was reviewed, but a specific official Hectic product detail page was not located.
- FragranceGems' EU guide identifies itself as an independent authorized Bujairami retailer and lists Hectic Extrait de Parfum: https://bujairamiperfumes.eu/
- Luxembourg retailer PerfumeMarket lists Hectic 100 ml and UPC 9362014000157, but its product title says Extrait while the URL slug says EDP: https://perfumemarket.lu/en/products/bujairami-hectic-100ml-edp
- Because of this concentration conflict and lack of a located official product page, Hectic remains a discovery candidate. No canonical product or variant was created.

### Arabiyat Prestige — Mahd Al Dhahab Extrait
- Retailer listings distinguish Mahd Al Dhahab Extrait from the standard Mahd Al Dhahab: https://fenicethebrand.pt/collections/arabiyat-prestige and https://arabicparfums.com/products/mahd-al-dhahab-extrait-arabiyat-prestige
- Parfumo independently records a 2026 Extrait release: https://www.parfumo.com/Perfumes/arabiyat-prestige/mahd-al-dhahab-extrait
- This may be a distinct concentration/release, not merely a bottle-size variant. No canonical row was created pending authoritative brand confirmation and a clear identity/variant decision.

The harvest overlay now records these cross-checks and the reason for holding both candidates outside the canonical seed.


## Pass 32 — Bujairami Hectic official identity verification (2026-11-08)

- Added **Hectic** as a canonical Bujairami fragrance name after locating the official brand product page: https://bujairami.com.au/products/hectic-inspired-by-louis-vuitton-imagination-extrait .
- The official product page confirms the product name and note profile but does not expose a clear concentration or bottle size in the extracted page.
- A Luxembourg retailer page calls it 100 ml Extrait de Parfum and publishes UPC 9362014000157, but the URL slug says EDP. An EU retailer guide also lists it as Extrait. Due to this conflict, no concentration, size or GTIN is imported and no variant row is created.
- Synchronized the Bujairami family registry and harvest overlay; added `backend/tests/test_bujairami_catalog.py` to guard official provenance and prevent inferred commercial/variant fields.
- Current catalog count after this identity-only addition: **1,922 canonical identities; 245 explicit variants**. CI remains unverified on the current PR head.


## Pass 33 — Mahd Al Dhahab Extrait source gate (2026-11-08)

- Confirmed multiple retailer listings and an independent perfume database distinguish **Mahd Al Dhahab Extrait** from the existing **Mahd Al Dhahab EDP**. The Extrait is presented as a 2026 release, and retailers identify a 60 ml presentation.
- Evidence reviewed includes Fenice, Arabic Parfums, ParfumGroup, Parfimo, FragranceNet and Fragrantica. These are corroborating retailer/database sources, not the Arabiyat Prestige brand's own product detail page.
- Kept the Extrait outside the canonical seed until an official brand or clearly authorized primary distributor product detail is confirmed. It must not be merged into the EDP as a concentration variant without authoritative evidence that the product identity is one and the same.
- The candidate overlay now explicitly records this evidence gate and its no-inference rule.


## Pass 34 — Arabiyat Prestige Mahd Al Dhahab Extrait primary-source confirmation (2026-11-08)

- The source gate is now closed. The MyPerfumes Europe Arabiyat perfumes store, titled as the official store, exposes a dedicated product detail page for **Arabiyat Prestige — Mahd Al Dhahab Extrait De Parfum — 60ML**: https://eu.myperfumes.ae/en-de/products/mahd-al-dhahab-extrait .
- The official store separately lists **Mahd Al Dhahab EDP 100ML** and **Mahd Al Dhahab Extrait De Parfum 60ML**, confirming these are separate fragrance identities/presentations rather than one generic EDP with an inferred concentration option.
- Added Mahd Al Dhahab Extrait as a distinct canonical product and added one explicit 60 ml Extrait de Parfum variant. The existing Mahd Al Dhahab EDP was not merged or renamed.
- Fenice retailer and Parfumo independent database provide corroboration for the distinct Extrait release.
- Added `backend/tests/test_arabiyat_prestige_extrait.py` for canonical separation, official source provenance, exact 60 ml Extrait variant, registry format and identity uniqueness.
- Catalog totals after this addition: **1,923 canonical identities; 246 explicit variants**. No retailer offer, price, stock, shipping cost or GTIN was imported.


## Pass 35 — Arabiyat Prestige official-store collection reconciliation (2026-11-08)

- Reviewed the MyPerfumes Europe official Arabiyat Prestige collection and followed individual product detail links. The collection page lists 29 products in its currently visible listing.
- Compared those names with the existing canonical seed. Twenty source-listed identities were missing and have now been added: Mahd Al Dhahab, Nyla Sherbet, Fahad Regal, Aristo, Bóis Blanc, Cherry Musk, Marasi For Her, Marasi For Him, Swar Serpentine, Swar D'Amour, Cursed, Ramad Oriental, Kohl Opulence, Kohl Luminous, Gelato Raspberry Ripple, Gelato Black Current Lolly, La Di Da For Her, La Di Da For Him, Uhud and Safa.
- Added explicit variants based on the official-store product listing: Nyla Sherbet 80 ml EDP; the other 19 entries 100 ml EDP. Mahd Al Dhahab EDP 100 ml remains distinct from the already added Mahd Al Dhahab Extrait 60 ml.
- Added official product detail URLs, updated the harvest overlay and Arabiyat Prestige family registry, and created `backend/tests/test_arabiyat_prestige_official_store.py` to verify identity provenance, variant size/concentration, registry format and uniqueness.
- No price, stock, shipping cost, retailer offer or GTIN was imported.
- Catalog totals after this pass: **1,943 canonical identities; 266 explicit variants**.
