

### Mykonos: first-party Indonesian collection reconciliation (8 November 2026)

The brand-owned Indonesian storefront was checked across all four pages of its main `/collections/all` listing. It reports 54 products in total. The four pages list the current assortment, including the following explicit concentration/size titles:
- Page 1: Aphrodite (Extrait 50/100 ml), Baby Love (EDP 50 ml), Black Opera (Extrait 100 ml), Bonfire Vanilla (Extrait 50 ml), Cafe Drops (Extrait 50 ml), California Blue (Extrait 50/100 ml), California Club (Extrait 50 ml), California (Extrait 50/100 ml), Caramel Fudge Cookie (EDP 50 ml), Coconut Dreams (Extrait 50 ml), Conquer (Extrait 50/100 ml), Constantine (Extrait 50 ml), Crimson (Extrait 100 ml), Dark Secret (Extrait 100 ml), Dreamscape (Extrait 50/100 ml).
- Page 2: Enchanted (Extrait 50/100 ml), Hawaiian Crush (Extrait 50 ml), Imperium (Extrait 100 ml), Inception (Extrait 50/100 ml), Inferno (Extrait 50/100 ml), Luminos (Extrait 50 ml), Marbella (Extrait 50/100 ml), Matcha Latte (Extrait 50 ml), Mayfair (Extrait 50/100 ml), Milk Drops (Extrait 50 ml), Monaco Royale (Extrait 50/100 ml), Moroccan Vanilla (Extrait 100 ml), Musk Aura (Extrait 100 ml), Nautilus (Extrait 100 ml), On The Rocks (Extrait 100 ml).
- Page 3: Paradise (Extrait 50 ml), Penthouse (Extrait 50/100 ml), Pink Beach (EDP 50 ml), Pink Drops (Extrait 50 ml), Reflection Elixir (Extrait 50 ml), Reflection (Extrait 50/100 ml), Royal Ispahan (Extrait 50/100 ml), Satin Blanc (Extrait 100 ml), Senja (Extrait 50 ml), Silent Whisper (Extrait 50/100 ml), Slow Living (EDP 50 ml and Extrait 100 ml), Sorrento (Extrait 50/100 ml), Sparkling Rosé (Extrait 100 ml), Stilettos (EDP 50 ml), plus a separate 15 ml travel-size item.
- Page 4: Untamed (Extrait 100 ml), Utopia (Extrait 100 ml), Vanilla Clouds (Extrait 50 ml), Verve (Extrait 50 ml), Xoxo Rosy (EDP 50 ml), MyEgo (Extrait 50/100 ml), Empire x RRQ (Extrait 50/100 ml), Glitch (Extrait 50/100 ml), and Invade (Extrait 50 ml).

The official brand-owned size collections report 37 items in the 50 ml collection and 26 in the 100 ml collection. These counts overlap where a perfume is offered in both sizes and must not be summed as unique identities. The main 54-product listing and the size collections are the first-party evidence baseline for the current Indonesian assortment.

The 19 no-variant/no-size identities identified in the seed audit (Sansa, Tea Poetry, Affair, Only You, Shades Perfume, Chai Crema Latte, Jynx, Rouge, Seven Roses, Ivory, Blossom, Zora, Down to Earth, When in Paris, Pandan Sticky Rice, Pistachio Cream Cake, Blaze, Memoir of Meri and Once Upon Don) do not appear in the four current main collection pages. The authorized EU retailer does publish individual product pages for them, with EU retail sizes/concentrations recorded in the previous table, but those EU pages do not override the brand-owned current assortment or prove that the same variants are offered in Indonesia.

**Final Mykonos seed decision for this pass:** retain the existing 72 canonical identities and 73 explicit variants. The current 73 variants remain internally consistent; the 19 legacy/regionally listed identities remain without guessed variants. Do not delete identities merely because they are absent from the current Indonesian assortment; they may be legacy, regional, collaboration or archived products. Do not mark them discontinued without first-party evidence.

First-party references:
- Main assortment page 1: https://officialmykonos.com/collections/all
- Main assortment page 2: https://officialmykonos.com/collections/all?page=2
- Main assortment page 3: https://officialmykonos.com/collections/all?page=3
- Main assortment page 4: https://officialmykonos.com/collections/all?page=4
- 50 ml collection: https://officialmykonos.com/collections/50ml-colection
- 100 ml collection: https://officialmykonos.com/collections/100ml-collection


### Mykonos: official 15 ml travel-size variants (8 November 2026)

The official Mykonos product page **Mykonos - Travel Size 15ML** exposes a selector listing 18 named fragrance options. These are travel-size variants of existing canonical fragrances, not 18 new perfume identities. The 18 options were reconciled against the existing Mykonos product IDs and one 15 ml variant was added to each matching identity:

- Dark Secret — 15 ml
- Musk Aura — 15 ml
- Sansa — 15 ml
- Satin Blanc — 15 ml
- Sparkling Rosé — 15 ml
- Black Opera — 15 ml
- Moroccan Vanilla — 15 ml
- Affair — 15 ml
- Utopia — 15 ml
- Tea Poetry — 15 ml
- Hawaiian Crush — 15 ml
- On The Rocks — 15 ml
- Royal Ispahan — 15 ml
- Crimson — 15 ml
- California — 15 ml
- California Blue — 15 ml
- Penthouse — 15 ml
- Monaco Royale — 15 ml

- Evidence page: https://officialmykonos.com/products/mykonos-sansa-edp-travel-size-15ml
- Each new variant records the same evidence URL and the 15 ml size.
- Concentration is carried onto the 15 ml variant only where the canonical identity already has an explicitly sourced concentration. Sansa, Affair and Tea Poetry remain without a concentration; none was inferred from the generic travel-size page.
- No new canonical identities were created and no existing variant was duplicated.
- Mykonos now has 72 canonical identities and **91 explicit variants** (18 new 15 ml variants).
- The count of Mykonos identities without any explicit variant is now 16 (down from 19). This is not a claim that the Mykonos catalog is complete: all remaining no-variant identities and the full size/concentration matrix still require individual product-page verification.
- Regression test added to `backend/tests/test_requested_brand_catalog_coverage.py` to check all 18 named 15 ml variants, source evidence, and concentration handling.

The travel-size listing is a product-detail page with selectable scent options; it provides strong official evidence for the 15 ml option names and size, but it does not independently establish a concentration for every scent. Source: https://officialmykonos.com/products/mykonos-sansa-edp-travel-size-15ml


### CI trigger correction — 8 November 2026

A follow-up review of GitHub Actions trigger semantics found that `pull_request.branches` filters the **base/target branch**, not the source/head branch. PR #439 already targets `catalog/consolidated-brand-catalog-2026-11-08`, which is present in that filter. The requested-brand source branch was therefore removed from the `pull_request.branches` list and added to the workflow's `push.branches` list instead, so direct commits to this working branch run catalog validation. Workflow change commit: `bac60ee7d1a37f225cccd2570de788f66211682e`.

The GitHub Actions connector returned no run for the immediately preceding commit when checked. A successful run for the corrected trigger and latest head must still be observed before claiming CI passed.


**Concentration handling clarification:** the 15 ml travel-size listing explicitly confirms the size and scent names, but does not state concentration for each selector option. Therefore concentration is intentionally left blank on **all 18 new 15 ml variant rows**, even where the parent identity has a concentration from a different listing. This avoids transferring/inferencing concentration onto a size variant without variant-level evidence. The regression test enforces this.


**Provenance placement:** the travel-size page URL is stored on each 15 ml variant row as `source_evidence_url`; it is not substituted for the canonical identity's `source_url` or product-level provenance.


## Current reconciled seed snapshot — 8 November 2026

The branch `catalog/requested-brand-harvest-2026-11-08` was re-read after the historical brand-audit notes above were written. The current JSON is authoritative for the present branch snapshot:

- Canonical identities: **2,061**
- Explicit variants: **291**
- Fragrance families: **34**
- Identities belonging to the 20 requested brands: **2,058**
- Structural checks: **0** duplicate product IDs, **0** duplicate variant IDs, **0** duplicate brand/name pairs, **0** orphan variants, and **0** variants with missing or invalid sizes.

These totals supersede earlier intermediate totals (including 266 and 273 variants) wherever those numbers were presented as the current catalog total. Historical passages above are retained as a dated audit trail and should not be read as the latest snapshot. The catalog remains a source-backed identity seed; these structural checks do not prove exhaustive coverage of every brand's current or historical fragrance range.


### Follow-up first-party source audit — 9 November 2026

A focused reconciliation compared selected current official pages against the exact canonical seed. This section records confirmed leads and scope limits; it does not treat raw collection product counts as perfume identity targets.

- **Armaf — Uniq Oud Forever:** an official individual fragrance page exists at https://armaf.com/products/uniq-oud-forever-spr. The existing canonical identity is `SH-ARMAF-f650f6a8`, currently listing-backed from the official all-perfumes collection. This is a provenance-review candidate only; reuse the existing identity and do not append a duplicate. The page evidence currently checked confirms the name and fragrance classification, but its variant size/concentration fields were not sufficiently explicit in the accessible page text to create a new variant.
- **Armaf — Uniq Effects of Uniq:** official individual page https://armaf.com/products/uniq-effects-of-uniq-spr; this name is absent from the canonical Armaf subset. The page labels it as a fragrance and identifies the target gender as men. It is a new-identity candidate pending source URL/schema validation and a second check of variant details. No size or concentration is added from the evidence inspected in this pass.
- **Lattafa — Asad Polar:** the official product page https://lattafa.com/product/asad-polar/ explicitly states 100 ml and describes the item as a fragrance. Exact canonical-name matching finds no current Asad Polar identity in the seed. It is a new identity candidate; concentration is left unspecified because the accessible detail text did not state it. Do not create a variant until the product row and source are added through a dedicated patch with the explicit 100 ml evidence.
- **Arabiyat Prestige — Lychee Musk:** official product page https://arabiyatprestige.com/products/arabiyat-prestige-lychee-musk-edp-100ml-unisex explicitly states Eau de Parfum, 100 ml and unisex. The seed already contains exactly one identity with product ID `SH-ARABIYAT-PRESTIGE-0b061839`, but its current identity source is a third-party range page. This is a provenance-upgrade candidate, not a new identity; reuse that product ID and create/reconcile the 100 ml EDP variant only after checking existing variants.
- **Maison Asrar:** the official all-products page currently displays 130 products. Its navigation also exposes separate Room Spray and Home Fragrances areas, so 130 cannot be interpreted as 130 perfume identities. Product-by-product classification is required before treating the difference against the seed as a gap.
- **Al Wataniah:** the official all-products page displays 103 products at the current read (an earlier indexed snapshot displayed 108). Its navigation explicitly separates perfume collections from Perfumed Body Mist and Air Freshener. The seed's 86 identities are tied to the Classic, Eternal, Niche and Munchies collection audit; the aggregate page count is a review lead, not an add count.
- **Armaf:** the official all-fragrances collection displays 464 products, but the same page's concentration filters enumerate body lotion, body mist, body spray, deodorant, shower gel, shampoo and soap as well as Eau de Parfum/EDT/Extrait. Those non-perfume categories must not be harvested as canonical fragrance identities. The new-launch collection also includes gift sets and sprays, so its results require item-level filtering.
- **Lattafa and Arabiyat Prestige:** the official current pages show new items such as Asad Polar and Lychee Musk. Existing product presence, region-specific listings, and page variants need reconciliation before changes; third-party listings remain discovery evidence only and must not silently replace first-party proof.

The audit deliberately leaves candidate rows unmodified in this pass. The next catalog change should be a separate, small harvest PR that adds only the individually confirmed absent identities (after checking all existing aliases/families), and a separate provenance-only PR for existing rows. No prices, stock, or retailer offers are inferred from brand pages.


### Catalog delta — three official-page reconciliations (9 November 2026)

This block adds two missing fragrance identities and upgrades one existing identity using individual brand-owned detail pages:

- **Armaf — Uniq Effects of Uniq:** added once from https://armaf.com/products/uniq-effects-of-uniq-spr. The page explicitly labels it as a fragrance and identifies it for men. The US storefront page does not expose bottle size or concentration in its accessible product text; no variant or concentration is inferred. The regional UAE storefront separately describes an EDP 100 ml version, but that regional specification is not mixed into the US-source record.
- **Lattafa — Asad Polar:** added once from https://lattafa.com/product/asad-polar/. The official product detail explicitly states 100 ML and fragrance type Men. The accessible official detail does not state concentration, so the product and 100 ml variant remain without a concentration value.
- **Arabiyat Prestige — Lychee Musk:** the existing identity `SH-ARABIYAT-PRESTIGE-0b061839` was retained and its provenance upgraded to https://arabiyatprestige.com/products/arabiyat-prestige-lychee-musk-edp-100ml-unisex. The official detail explicitly states Eau De Parfum, 100 ML and Unisex. One 100 ml EDP variant was added; no second canonical identity was created.

No prices, stock status, retailer offers, or shipping claims are copied into the catalog. Transient sales information is not product identity data.



### Swiss Arabian new-launch reconciliation — 9 November 2026

Four absent canonical fragrance identities were added from Swiss Arabian's official individual product pages:

- **Shaghaf Oud Marine:** official product detail https://swissarabian.com/collections/new-launches/products/shaghaf-oud-marine. Its 75 ml Eau de Parfum specification is explicitly confirmed by Swiss Arabian's own Collector's Edition III detail page, which lists the included Shaghaf Oud Marine EDP 75 ml.
- **Echoes of St. Moritz:** official product detail https://swissarabian.com/collections/new-launches/products/echoes-of-st-moritz. Its 100 ml Extrait de Parfum specification is explicitly confirmed by the same official Collector's Edition III page.
- **Shaghaf Nectar Blush:** official product detail https://us.swissarabian.com/collections/new-launches/products/shaghaf-nectar-blush. The official US product title specifies Eau de Parfum 75 ml.
- **Patchouli 01:** official product detail https://us.swissarabian.com/products/patchouli-01. The official US product title specifies Extrait de Parfum 50 ml.

Each identity received one matching size/concentration variant and was added to the existing Swiss Arabian family registry. The Collector's Edition III was intentionally excluded as a separate identity because the official page describes it as a two-fragrance set containing Echoes of St. Moritz and Shaghaf Oud Marine, not a standalone perfume.



### Swiss Arabian new-launch reconciliation — continuation, 9 November 2026

A second pass through page 2 of the official New Launches collection found five more absent identities:

- **Enigma of Taif:** individual official page https://swissarabian.com/collections/new-launches/products/enigma-of-taif explicitly states 100 ml. The accessible brand-owned page does not state concentration, so it remains unspecified.
- **Shaghaf Amber Infusion:** official page https://swissarabian.com/collections/new-launches/products/shaghaf-amber-infusion explicitly states Extrait de Parfum 75 ml.
- **Soul of Bali:** official page https://swissarabian.com/collections/new-launches/products/soul-of-bali explicitly states Extrait de Parfum 100 ml.
- **Vanilla 01:** official US page https://us.swissarabian.com/products/vanilla-01 identifies Extrait de Parfum 50 ml.
- **Tobacco 01:** official US page https://us.swissarabian.com/products/tobacco-01 identifies Extrait de Parfum 50 ml.

Each was added once with a matching size variant. Enigma of Taif deliberately has no concentration field because the individual brand-owned page inspected does not expose one. Gift sets on the same new-launch collection were excluded.



### Maison Asrar: ten new-arrival individual-page provenance upgrades (9 November 2026)

The brand-owned Maison Asrar new-arrival collection lists 81 products. Its first twelve entries were checked against the existing catalog. Belgravia and Regent already had individual official product-page evidence. The following ten existing canonical identities were upgraded from collection/listing-level provenance to their own individual official product pages, without creating duplicate identities:

- **Ameer** — https://maisonasrar.com/products/ameer
- **DXB Jumeirah** — https://maisonasrar.com/products/dxb-jumeirah
- **Last Swim** — https://maisonasrar.com/products/last-swim
- **Silent Surge** — https://maisonasrar.com/products/silent-surge
- **Veyra** — https://maisonasrar.com/products/veyra
- **Infina** — https://maisonasrar.com/products/infina
- **Librae** — https://maisonasrar.com/products/librae
- **Harmony** — https://maisonasrar.com/products/harmony
- **Fairyland** — https://maisonasrar.com/products/fairyland
- **Whisper** — https://maisonasrar.com/products/whisper

The inspected individual pages confirm the fragrance names and standalone product pages. Their accessible page content did not explicitly state bottle size or concentration, so no size variants or concentration values were invented. The collection's note pyramids and merchandising descriptors were not treated as size/concentration evidence. Room sprays, home-fragrance products and sets remain outside the perfume identity scope. The collection page currently reports 81 products; this pass only verifies the first twelve visible new-arrival entries and is not a full 81-product reconciliation.

Regression coverage was added in `backend/tests/test_maison_asrar_new_arrival_evidence.py` for the ten official detail URLs, provenance status, and the deliberate absence of unsupported variants.


### Bujairami: four original fragrances verified from individual product pages (9 November 2026)

The official Bujairami EU storefront's Shop page identifies four original fragrances and labels their concentrations: Gold Coast Shiraz (EDP), G’Day (Extrait de Parfum), Midnight in Melbourne (EDP), and Sunrise in Sydney (EDP). Each linked individual product page confirms a 100 ml size. The four canonical identities already existed in the seed, so they were upgraded in place and given one 100 ml variant each; no duplicate products were created.

- Gold Coast Shiraz — https://bujairami.eu/product/gold-coast-shiraz/
- G’Day — https://bujairami.eu/product/gday/
- Midnight in Melbourne — https://bujairami.eu/product/midnight-in-melbourne/
- Sunrise in Sydney — https://bujairami.eu/product/sunrise-in-sydney/

The concentration labels for Gold Coast Shiraz, Midnight in Melbourne, and Sunrise in Sydney are stated on the official Shop page; their individual detail pages confirm the 100 ml size. G’Day's individual page explicitly states Extrait de Parfum with 35% essence and 100 ml. No price or stock data was copied into the catalog. This is a focused verification of four original fragrances, not a full reconciliation of the much larger Bujairami inspired-fragrance assortment.


### Bujairami UAE: eight recent arrivals upgraded to individual product-page evidence (9 November 2026)

The brand-owned Bujairami UAE homepage highlights eight recent arrivals. All eight names were already present in the catalog, so the existing canonical identities were upgraded in place to their individual product pages. The official product-page titles confirm the Bujairami product names; the three cards explicitly marked Extrait are recorded as Extrait de Parfum. The accessible individual pages do not state bottle sizes, so no variants were added.

- Tea Splash — https://bujairami.ae/products/tea-splash-inspired-by-rain-tea-louis-vuitton
- V-Luxe — https://bujairami.ae/products/v-luxe-inspired-by-libre-vanille-couture-yves-saint-laurent
- ACE — https://bujairami.ae/products/ace-inspired-by-uomo-born-in-roma-coral-fantasy-valentino
- Last Kingdom — https://bujairami.ae/products/last-kingdom-inspired-by-argentina-memo-paris-extrait (Extrait de Parfum)
- Darkwood — https://bujairami.ae/products/darkwood-inspired-by-chandigarh-express-ex-nihilo-extrait (Extrait de Parfum)
- Chic Wood — https://bujairami.ae/products/chic-wood-inspired-by-cedar-chic-carolina-herrera
- Delulu — https://bujairami.ae/products/delulu-inspired-by-the-hedonist-extrait-de-parfum-ex-nihilo-extrait (Extrait de Parfum)
- Suns Out — https://bujairami.ae/products/suns-out-inspired-by-my-way-sunny-vanilla-giorgio-armani

No bottle size, concentration beyond the three explicit Extrait labels, price or stock status was inferred. The product descriptions' "inspired by" references are retained as marketing context, not treated as equivalence to the referenced designer fragrances.


### Velixir: official storefront and 20 individual fragrance pages reconciled (9 November 2026)

The brand-owned Velixir Parfums storefront identifies 20 current products. All 20 were matched to existing canonical identities and upgraded in place to their individual product-page URLs. The product-page titles confirm the concentration for each fragrance. Sixteen Eau de Parfum pages explicitly offer both 35 ml and 100 ml sizes; those 32 variants were added and mirrored in the product and family-registry format lists. The four Extrait de Parfum products (Panacea, Comus, Orpheus, Ether) did not expose explicit sizes in the inspected page content, so no variants were invented for them.

Current storefront products reconciled:
- Panacea — Extrait de Parfum; size not explicitly stated
- Comus — Extrait de Parfum; size not explicitly stated
- Harmonia — Eau de Parfum; 35 ml and 100 ml
- Nyx — Eau de Parfum; 35 ml and 100 ml
- Morpheus — Eau de Parfum; 35 ml and 100 ml
- Aphrodite — Eau de Parfum; 35 ml and 100 ml
- Artemis — Eau de Parfum; 35 ml and 100 ml
- Asteria — Eau de Parfum; 35 ml and 100 ml
- Concordia — Eau de Parfum; 35 ml and 100 ml
- Himeros — Eau de Parfum; 35 ml and 100 ml
- Demeter — Eau de Parfum; 35 ml and 100 ml
- Galatea — Eau de Parfum; 35 ml and 100 ml
- Hera — Eau de Parfum; 35 ml and 100 ml
- Icarus — Eau de Parfum; 35 ml and 100 ml
- Persephone — Eau de Parfum; 35 ml and 100 ml
- Poseidon — Eau de Parfum; 35 ml and 100 ml
- Uranus — Eau de Parfum; 35 ml and 100 ml
- Selene — Eau de Parfum; 35 ml and 100 ml
- Orpheus — Extrait de Parfum; size not explicitly stated
- Ether — Extrait de Parfum; size not explicitly stated

The storefront collection page shows all 20 as sold out/unavailable at the time inspected. This is transient store availability, not a reason to remove the canonical identities. No current price or stock values were copied into the catalog. Eight additional Velixir identities remain in the seed but are not in the 20-item current storefront listing; they were not altered or treated as current availability evidence.


### Games of Spades: official Jo Milano Paris product-page reconciliation (9 November 2026)

Jo Milano Paris is the brand owner behind the Games of Spades line. Twenty-eight existing catalog identities were matched to their own official Jo Milano Paris product pages and upgraded to individual-page provenance. The existing **Ace** name remains explicitly at listing-level confidence: the current official store did not expose an individual Ace product page, so its evidence was corrected to the distributor catalog lead rather than incorrectly pointing at the King page.

Three additional standalone fragrances were added from individual official product pages, with only the sizes and concentrations explicitly stated by Jo Milano Paris:
- **Blue Sapphire** — Parfum; 90 ml and 30 ml
- **Emerald Extrait** — Extrait de Parfum; 90 ml, 50 ml and 10 ml
- **Rouge Extrait** — Extrait de Parfum; 100 ml, 30 ml and 10 ml

Gift sets and coffrets remain excluded as standalone perfume identities. Other Jo Milano Paris lines outside the Games of Spades family were not added in this focused pass.

## Authoritative catalog reconciliation — 9 November 2026

The catalog JSON and family registry were fetched directly from the exact PR branch and parsed independently. This is the authoritative snapshot for the current branch; the earlier 8 November figures above remain historical checkpoints and are superseded.

- Canonical fragrance identities: **2,081**
- Explicit variants: **358**
- Fragrance families: **34**
- Requested-brand identities across the 20 brands: **2,078**
- Unique product IDs: **2,081 / 2,081**
- Unique variant IDs: **358 / 358**
- Duplicate normalized brand/name pairs: **0**
- Orphan variants: **0**
- Variants with missing or non-positive sizes: **0**
- Requested-brand identities missing `source_url`: **0**
- Requested-brand identities with an unsupported `identity_status`: **0**
- Catalog identities not covered by the family registry under accent/punctuation normalization: **0**

Per-brand canonical identity counts:
- Velixir 28; Mykonos 72; Maison Asrar 120; Khadlaj 116; Bujairami 142
- Paris Corner 246; Assaf 140; Al Wataniah 86; Armaf 191; French Avenue 119
- Arabiyat Prestige 118; Gulf Orchid 23; Swiss Arabian 41; Games of Spades 32; Lattafa 115
- Afnan 87; Aromatix 12; Maison Alhambra 207; Zimaya 76; Al Haramain 107

The 20 requested brands total **2,078** identities. The remaining three identities are outside that requested set (Giorgio Armani 1 and Al Ambra 2). These checks establish internal structural consistency and provenance-field coverage; they do **not** prove that every brand's complete worldwide or historical assortment has been harvested. The catalog remains a canonical identity seed, not a live offer inventory.

The two successful `validate-catalog-seed` Actions runs recorded for catalog commit `f64c61f1558df42ddd50cf6067b70ef0df6c8d4a` validate the unchanged catalog/test snapshot. This documentation-only reconciliation does not modify catalog data or production code.

### Gulf Orchid: official storefront detail-page harvest (9 November 2026)

The brand-owned Gulf Orchid storefront was checked against the existing seed and its New Arrivals listing. Five existing identities were upgraded to individual product-page evidence, and nine further standalone fragrances were added as canonical identities. The product detail pages explicitly state Eau de Parfum and bottle size for every entry below, so one matching explicit variant was recorded per identity:

- Vanilla Addiction — 100 ml EDP (existing identity upgraded)
- Mango Ice — 100 ml EDP (existing identity upgraded)
- Sweet Heaven 20ML — 20 ml EDP (existing identity upgraded; retained as a size-specific canonical label from the seed)
- Pink Marshmallow — 100 ml EDP (existing identity upgraded)
- Coco Blanco — 100 ml EDP (existing identity upgraded)
- Belle — 100 ml EDP (new identity)
- Amour — 100 ml EDP (new identity)
- Chic — 100 ml EDP (new identity)
- Cloud 9 — 100 ml EDP (new identity)
- Phantom — 100 ml EDP (new identity)
- Flamma — 100 ml EDP (new identity)
- Vortex — 100 ml EDP (new identity)
- Rosalia — 100 ml EDP (new identity)
- Maestro — 100 ml EDP (new identity)

The corresponding family-registry entries and product format lists were synchronized. Regression tests assert official detail URLs, identity status, concentration, size and one-to-one variant provenance. No price, stock state, or unverified size was added. The official New Arrivals listing also includes Maison Asrar products; those were not misclassified as Gulf Orchid. Other Gulf Orchid collection names without individual fragrance evidence remain listing-level and were not upgraded.

Primary source pages:
- Official perfume collection: https://shop-gulforchid.com/collections/perfume
- Official New Arrivals: https://shop-gulforchid.com/collections/new-arrivals
- Vanilla Addiction: https://shop-gulforchid.com/products/vanilla_addiction_eau_de_parfum
- Mango Ice: https://shop-gulforchid.com/products/mango_ice_eau_de_parfum
- Sweet Heaven 20 ml: https://shop-gulforchid.com/products/sweet-heaven-by-gulf-orchid-eau-de-parfum-20ml
- Pink Marshmallow: https://shop-gulforchid.com/products/pink-marshmallow
- Coco Blanco: https://shop-gulforchid.com/products/coco-blanco
- Belle: https://shop-gulforchid.com/products/belle
- Amour: https://shop-gulforchid.com/products/amour
- Chic: https://shop-gulforchid.com/products/chic
- Cloud 9: https://shop-gulforchid.com/products/cloud-9
- Phantom: https://shop-gulforchid.com/products/phantom
- Flamma: https://shop-gulforchid.com/products/flamma
- Vortex: https://shop-gulforchid.com/products/vortex
- Rosalia: https://shop-gulforchid.com/products/rosalia
- Maestro: https://shop-gulforchid.com/products/maestro

## Post-Gulf Orchid authoritative snapshot — 9 November 2026

After the Gulf Orchid official-page harvest, the catalog and family registry were fetched again from the branch and independently revalidated. This snapshot supersedes the earlier 2,081 / 358 totals above:

- Canonical fragrance identities: **2,090**
- Explicit variants: **372**
- Fragrance families: **34**
- Identities across the 20 requested brands: **2,087**
- Gulf Orchid: **32 identities**, of which **14** have individual product-page evidence and **14** have explicit size variants
- Duplicate product IDs, duplicate variant IDs, duplicate normalized brand/name pairs: **0**
- Orphan variants, invalid/missing variant sizes, missing requested-brand source URLs, unsupported requested-brand identity statuses: **0**
- Identities not represented in the family registry: **0**

The three identities outside the requested 20 brands remain Giorgio Armani (1) and Al Ambra (2). The catalog remains an identity seed, not an offer inventory. A failed CI run occurred on the intermediate catalog-only commit before the matching family-registry and regression-test updates landed; subsequent runs on the completed data/test changes are the relevant validation.

### Aromatix: official French Avenue collection reconciliation (9 November 2026)

The official French Avenue Aromatix Collection currently lists ten individual fragrances. All ten were matched to existing Aromatix canonical identities and upgraded from listing-level evidence to their own individual product pages:

- Carnal Desire — Eau de Parfum, 100 ml
- Forbidden Fruit — Eau de Parfum, 100 ml
- Frostbite — Extrait de Parfum, 100 ml
- Magnetiq — Eau de Parfum, 100 ml
- Naughty Dates — Eau de Parfum, 100 ml
- Platine Blanc (official page spells the product title “Plantine Blanc”) — individual page verified; size and concentration are not stated in the extracted product specification, so no variant or concentration was added
- Royal Taboo — Extrait de Parfum, 100 ml
- Sun Kissed — Eau de Parfum, 100 ml
- Teas Me — Eau de Parfum, 100 ml
- X Xandal — Extrait de Parfum, 100 ml

Nine explicit 100 ml variants were added with individual product-page provenance. The family registry was synchronized. The two Aromatix Summer Vibes entries remain excluded as multi-fragrance gift sets rather than being treated as standalone perfume identities. Existing Ora and Roza entries were not changed because the current official collection did not provide individual detail-page evidence for them.

Primary sources:
- Official Aromatix collection: https://frenchavenue.com/collections/aromatix
- Plantine Blanc: https://frenchavenue.com/products/aromatix-plantine-blanc
- Naughty Dates: https://frenchavenue.com/products/aromatix-naughty-dates
- Frostbite: https://frenchavenue.com/products/aromatix-frostbite
- Magnetiq: https://frenchavenue.com/products/aromatix-magnetiq
- Carnal Desire: https://frenchavenue.com/products/carnal-desire
- Teas Me: https://frenchavenue.com/products/aromatix-teas-me
- Royal Taboo: https://frenchavenue.com/products/royal-taboo
- X Xandal: https://frenchavenue.com/products/aromatix-x-xandal
- Forbidden Fruit: https://frenchavenue.com/products/aromatix-forbidden-fruit
- Sun Kissed: https://frenchavenue.com/products/aromatix-sunkissed

Regression tests were added to the catalog-seed validation workflow for all ten individual page URLs, explicit concentration/size fields, and the exclusion of gift sets.

## Latest structural snapshot after Aromatix reconciliation — 9 November 2026

The current branch catalog and family registry were parsed again after the Aromatix updates:

- Canonical identities: **2,090**
- Explicit variants: **381**
- Fragrance families: **34**
- Requested-brand identities: **2,087**
- Aromatix: **12 identities**, 10 with individual official product-page evidence; nine explicit 100 ml variants added in this pass
- Gulf Orchid: **32 identities**, 14 individually verified with 14 explicit variants
- Duplicate product IDs, variant IDs and normalized brand/name pairs: **0**
- Orphan variants, invalid sizes, missing requested-brand source URLs, invalid requested-brand evidence statuses: **0**
- Catalog identities missing from the family registry: **0**

The three identities outside the 20 requested brands remain Giorgio Armani (1) and Al Ambra (2). These are structural and provenance checks, not a claim of exhaustive worldwide or historical catalog completeness.

### Mykonos: official storefront product-page reconciliation (9 November 2026)

The official MYKONOS `/collections/all` storefront reports 54 listings across four pages. Fifty-three are standalone named fragrance products; the remaining listing is a shared **Travel Size 15ML** product page with selectable fragrance options, not a separate fragrance identity. All 53 named current-storefront fragrances were matched to their existing canonical identities and upgraded to individual product-page provenance. Nineteen additional Mykonos seed identities were retained as historical/listing-level records and were not falsely upgraded.

The 53 reconciled identities are: Aphrodite, Baby Love, Black Opera, Bonfire Vanilla, Cafe Drops, California Blue, California Club, California, Caramel Fudge Cookie, Coconut Dreams, Conquer, Constantine, Crimson, Dark Secret, Dreamscape, Enchanted, Hawaiian Crush, Imperium, Inception, Inferno, Luminos, Marbella, Matcha Latte, Mayfair, Milk Drops, Monaco Royale, Moroccan Vanilla, Musk Aura, Nautilus, On The Rocks, Paradise, Penthouse, Pink Beach, Pink Drops, Reflection Elixir, Reflection, Royal Ispahan, Satin Blanc, Senja, Silent Whisper, Slow Living, Sorrento, Sparkling Rosé, Stilettos, Untamed, Utopia, Vanilla Clouds, Verve, Xoxo Rosy, MyEgo, Empire x RRQ, Glitch and Invade.

All 53 product rows now use their own official product-detail URL as source, and existing 50 ml / 100 ml variant records are linked to the corresponding detail page. The shared 15 ml travel-size page explicitly lists selectable options including Dark Secret, Satin Blanc, Sparkling Rose, Sansa, Musk Aura, Black Opera, Moroccan Vanilla, Affair, Utopia, Tea Poetry, Hawaiian Crush, On The Rocks, Royal Ispahan, Crimson, California, California Blue, Penthouse and Monaco Royale. Existing 15 ml variants are retained only against this explicit option list and keep the shared travel-size page as their evidence URL.

Two source-page inconsistencies were deliberately not guessed away:
- **Vanilla Clouds:** the page title and URL call it Extrait de Parfum, but the product-description text calls it EDP. Its identity and 50 ml size are verified; concentration has been left unset pending authoritative clarification.
- **Slow Living:** the product page title explicitly distinguishes 50 ml EDP from 100 ml Extrait de Parfum. The two concentrations are represented at variant level, not flattened into one concentration for the whole identity.

The catalog still contains 72 Mykonos identities: 53 current named storefront fragrances and 19 retained older/listing-level identities. The official storefront reports all 54 listings out of stock at the time checked; no prices or live availability were copied into ScentHunter's canonical identity seed.

Primary source:
- Official all-products collection (54 listings): https://officialmykonos.com/collections/all
- Official 15 ml travel-size options: https://officialmykonos.com/products/mykonos-sansa-edp-travel-size-15ml
- Official collection pagination: https://officialmykonos.com/collections/all?page=2 ; https://officialmykonos.com/collections/all?page=3 ; https://officialmykonos.com/collections/all?page=4

Regression coverage verifies the 53 individual source URLs, identity status, source evidence for variants, the shared 15 ml options, and the unresolved Vanilla Clouds concentration conflict.

## Latest structural snapshot after Mykonos reconciliation — 9 November 2026

The current PR branch was fetched and parsed after the Mykonos storefront update:

- Canonical fragrance identities: **2,090**
- Explicit variants: **381**
- Fragrance families: **34**
- Requested-brand identities: **2,087**
- Mykonos: **72 identities total; 53 upgraded with individual official product-page evidence; 19 retained as listing-level / historical records**
- Duplicate product IDs, variant IDs and normalized brand/name pairs: **0**
- Orphan variants, invalid sizes and missing requested-brand source URLs: **0**
- All catalog identities remain represented in the family registry.

The new Mykonos test module is included in `.github/workflows/catalog-seed-validation.yml`. Its CI result must be checked on the final PR head before calling this block fully validated. The catalog totals did not change because this pass upgraded provenance for existing identities and corrected an uncertain concentration field; it did not add new fragrance identities or variants.

### Al Wataniah: official storefront detail-page reconciliation (9 November 2026)

The brand-owned Al Wataniah UAE storefront was checked across its All Products collection (103 listings) and the Classic, Eternal, Niche, Munchies, Perfumed Body Mist and Air Freshener collection navigation. Nineteen existing canonical fragrance identities were upgraded to individual product-page provenance:

- Kayaan Classic
- Kayaan Terra
- Special Oud
- Sabah Al Ward
- Kayaan Gold
- Kayaan Midnight
- Ain Emarat
- Royal Oak I
- Al Daiem
- Arya Peony Rose
- Arya
- Ain Emarat Extrait
- Sabah Al Ward Sugar
- Royal Oak II
- Al Daiem Elixir
- Ameerati
- Attar Al Wesal
- Praline Toffee
- Rose Eclat

Each now points to its own official `/products/` page and is marked `source_verified_name`. Existing identities and IDs were retained; no new canonical names or variants were invented in this pass. Ain Emarat and Ain Emarat Extrait remain separate identities. Existing individually verified Lemon Souffle and Choco Truffle records were preserved.

The official storefront separates Perfumed Body Mist and Air Freshener into distinct collections. Those categories were not imported as standalone fragrance identities. The All Products page also includes products not yet present in this seed; these remain candidates for further page-by-page review rather than being bulk-added from listing names. No commercial prices or stock data were copied into the catalog.

Primary source:
- Official All Products collection (103 listings): https://www.alwataniah.com/collections/all-products
- Official Collections navigation: https://www.alwataniah.com/collections
- Individual official product pages are recorded in the product catalog.

Regression tests cover all 19 detail-page URLs and verify that Ain Emarat and Ain Emarat Extrait remain distinct. The new test module is included in the catalog-seed GitHub Actions workflow.

### Afnan: official global storefront detail-page reconciliation (9 November 2026)

The official Afnan Global storefront was checked against its All Products collection (120 listings) and individual product pages. Fifteen existing catalog identities were upgraded to individual official product-page evidence:

- 9 PM
- 9 PM Pour Femme
- 9 PM Elixir
- 9 PM Rebel
- Abiyad Mukhallat
- Abiyad Musk
- Abiyad Sandal
- Adwaa Al Sharq
- Cherry Bouquet
- Delicious Bouquet
- Ebdaa Concentrated Perfume Oil
- Edict Amberythme
- Edict Musctique
- Edict Ouddiction
- Historic Doria

The five Abiyad / Ebdaa items are retained as fragrance oils, not deodorants or gift sets. Afnan's official navigation and collection page separately identify deodorants, gift sets, travel sets and perfume oils; these product types are not conflated. Existing product IDs and canonical identities were retained. No size or concentration variants were added in this provenance-only pass because the inspected pages did not provide a consistent complete set of structured size data for these 15 records.

The official Afnan Global collection currently reports 120 listings, which include perfume oils, deodorants, travel kits and gift sets. Only standalone fragrance identities belong in the canonical fragrance list. Additional listings remain for further item-by-item review.

Primary sources:
- Official Global All Products collection: https://afnan.com/collections/all
- Official 9 PM page: https://afnan.com/products/9-pm
- Official 9 PM Pour Femme page: https://afnan.com/products/9-pm-pour-femme
- Official 9 PM Elixir page: https://afnan.com/products/9-pm-elixir
- Official 9 PM Rebel page: https://afnan.com/products/9-pm-rebel

Regression tests cover all 15 individual page URLs and keep perfume oils separate from deodorant / gift-set listings.
