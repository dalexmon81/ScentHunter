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
Current catalog: 1153 canonical product identity records; 141 variant records.

## Current counts (catalog records, not proof of completeness)

Velixir: 28
Mykonos: 72
Maison Asrar: 121
Khadlaj: 41
Bujairami: 33
Paris Corner: 33
Assaf: 112
Al Wataniah: 22
Armaf: 190
French Avenue: 19
Arabiyat Prestige: 27
Gulf Orchid: 10
Swiss Arabian: 42
Games of Spades: 4
Lattafa: 19
Afnan: 55
Aromatix: 12
Maison Alhambra: 203
Zimaya: 71
Al Haramain: 37

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

The catalog has expanded to 1153 identities, but it is **not yet defensible to call it complete**. The strongest immediate gaps are Paris Corner and Khadlaj. Maison Asrar needs a name-level reconciliation because the current count exceeds the independent index count.


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
