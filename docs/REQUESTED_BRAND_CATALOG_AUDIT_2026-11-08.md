

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


### Mykonos: first 15 current assortment items upgraded to individual official-page evidence (9 November 2026)

The official Mykonos all-products collection currently reports 54 products. The first 15 collection entries were opened individually and reconciled against the existing canonical seed. All 15 already existed as canonical identities, so their product IDs and variant rows were preserved. Their `source_url` values now point to the matching first-party product-detail pages and `identity_status` is upgraded from `source_listed_name` to `source_verified_name`.

Verified identities:
- Aphrodite — https://officialmykonos.com/products/mykonos-aphrodite-extrait-de-parfum-50ml-100ml
- Baby Love — https://officialmykonos.com/products/mykonos-baby-love-edp-50ml
- Black Opera — https://officialmykonos.com/products/mykonos-black-opera-extrait-de-parfum-100ml
- Bonfire Vanilla — https://officialmykonos.com/products/mykonos-bonfire-vanilla-extrait-de-parfum-50ml
- Cafe Drops — https://officialmykonos.com/products/mykonos-cafe-drops-extrait-de-parfum-50ml
- California Blue — https://officialmykonos.com/products/mykonos-california-blue-extrait-de-parfum-50ml
- California Club — https://officialmykonos.com/products/mykonos-california-club-extrait-de-parfum-50ml
- California — https://officialmykonos.com/products/mykonos-california-signature-50ml
- Caramel Fudge Cookie — https://officialmykonos.com/products/mykonos-caramel-fudge-cookie-edp-50ml
- Coconut Dreams — https://officialmykonos.com/products/mykonos-coconut-dreams-extrait-de-parfum-50ml
- Conquer — https://officialmykonos.com/products/mykonos-conquer-extrait-de-parfum-100ml
- Constantine — https://officialmykonos.com/products/mykonos-constantine-extrait-de-parfum-50ml
- Crimson — https://officialmykonos.com/products/mykonos-crimson-extrait-de-parfum-100ml
- Dark Secret — https://officialmykonos.com/products/mykonos-dark-secret-extrait-de-parfum-100ml
- Dreamscape — https://officialmykonos.com/products/mykonos-dreamscape-extrait-de-parfum-50ml-100ml

The inspected product-page titles support the recorded product names, stated concentrations and listed 50/100 ml formats. No additional variants were created in this pass, and no prices or availability were copied. Existing 15 ml travel-size variants continue to retain the separate travel-size selector page as their own `source_evidence_url`; concentration was not inferred from that generic selector.

A regression test checks the 15 individual URLs, source status, concentrations, size variants and exactly one canonical row per identity. The remaining 57 Mykonos identities still require individual-page review; this is a first batch, not a claim of full brand completeness.


### Mykonos: second 15 current-assortment identities upgraded to individual official-page evidence (9 November 2026)

The second page of the official all-products collection was reconciled against the existing canonical seed. Fifteen existing identities were upgraded in place to their own brand-owned detail pages. No canonical product was appended and no product ID was changed:

- Enchanted — https://officialmykonos.com/products/mykonos-enchanted-extrait-de-parfum-50ml-100ml (50 ml and 100 ml)
- Hawaiian Crush — https://officialmykonos.com/products/mykonos-hawaiian-crush-extrait-de-parfum-50ml (50 ml)
- Imperium — https://officialmykonos.com/products/mykonos-imperium-extrait-de-parfum-100ml (100 ml)
- Inception — https://officialmykonos.com/products/mykonos-inception-extrait-de-parfum-50ml (50 ml and 100 ml)
- Inferno — https://officialmykonos.com/products/mykonos-inferno-extrait-de-parfum-100ml (50 ml and 100 ml)
- Luminos — https://officialmykonos.com/products/mykonos-luminos-extrait-de-parfum-50ml (50 ml)
- Marbella — https://officialmykonos.com/products/mykonos-marbella-extrait-de-parfum-100ml (50 ml and 100 ml)
- Matcha Latte — https://officialmykonos.com/products/mykonos-matcha-latte-extrait-de-parfum-50ml (50 ml)
- Mayfair — https://officialmykonos.com/products/mykonos-mayfair-extrait-de-parfum-100ml (50 ml and 100 ml)
- Milk Drops — https://officialmykonos.com/products/mykonos-milk-drops-extrait-de-parfum-50ml (50 ml)
- Monaco Royale — https://officialmykonos.com/products/mykonos-monaco-royale-extrait-de-parfum-50ml-100ml (50 ml and 100 ml)
- Moroccan Vanilla — https://officialmykonos.com/products/mykonos-moroccan-vanilla-extrait-de-parfum-100ml (100 ml)
- Musk Aura — https://officialmykonos.com/products/mykonos-musk-aura-extrait-de-parfum-100ml (100 ml)
- Nautilus — https://officialmykonos.com/products/mykonos-nautilus-extrait-de-parfum-100ml (100 ml)
- On The Rocks — https://officialmykonos.com/products/mykonos-on-the-rocks-extrait-de-parfum-100ml (100 ml)

All 15 official detail pages identify these products as Extrait de Parfum and state the size or size selector. The existing variant rows for the sizes displayed on the respective product pages now point to the corresponding individual detail page as `source_evidence_url`. Pre-existing 15 ml travel-size variants retain their separate selector-page evidence and are not assigned concentration from these detail pages.

A second regression test checks the 15 product URLs, source status, concentration, one canonical identity per name, and the corresponding explicit size variants. Together with the first batch, 30 of the 54 products in the current official Mykonos all-products collection now have individual detail-page provenance. This is not yet a complete audit of every remaining identity or of all legacy/region-specific products.


### Mykonos: final current-collection pages reconciled to individual official product pages (9 November 2026)

The third and fourth pages of the brand-owned 54-item all-products collection were opened and reconciled against the seed. The 23 standalone perfume identities below already existed in the catalog and were upgraded in place; no canonical product was duplicated.

- Paradise — https://officialmykonos.com/products/mykonos-paradise-extrait-de-parfum-50ml (Extrait de Parfum, 50 ml)
- Penthouse — https://officialmykonos.com/products/mykonos-penthouse-extrait-de-parfum-100ml (Extrait de Parfum, 50 ml and 100 ml)
- Pink Beach — https://officialmykonos.com/products/mykonos-pink-beach-edp-50ml (Eau de Parfum, 50 ml)
- Pink Drops — https://officialmykonos.com/products/mykonos-pink-drops-extrait-de-parfum-50ml (Extrait de Parfum, 50 ml)
- Reflection Elixir — https://officialmykonos.com/products/mykonos-reflection-elixir-extrait-de-parfum-50ml (Extrait de Parfum, 50 ml)
- Reflection — https://officialmykonos.com/products/mykonos-reflection-extrait-de-parfum-50ml-100ml (Extrait de Parfum, 50 ml and 100 ml)
- Royal Ispahan — https://officialmykonos.com/products/mykonos-royal-ispahan-extrait-de-parfum-50ml-100ml (Extrait de Parfum, 50 ml and 100 ml)
- Satin Blanc — https://officialmykonos.com/products/mykonos-satin-blanc-extrait-de-parfum-100ml (Extrait de Parfum, 100 ml)
- Senja — https://officialmykonos.com/products/mykonos-senja-edp-50ml (official page title states Extrait de Parfum, 50 ml; the legacy URL slug contains “edp” but is not used to override the displayed product title)
- Silent Whisper — https://officialmykonos.com/products/mykonos-silent-whisper-extrait-de-parfum-50ml-100ml (Extrait de Parfum, 50 ml and 100 ml)
- Slow Living — https://officialmykonos.com/products/mykonos-slow-living-edp-50ml (50 ml Eau de Parfum and 100 ml Extrait de Parfum)
- Sorrento — https://officialmykonos.com/products/mykonos-sorrento-extrait-de-parfum-50ml-100ml (Extrait de Parfum, 50 ml and 100 ml)
- Sparkling Rosé — https://officialmykonos.com/products/mykonos-sparkling-rose-extrait-de-parfum-100ml (Extrait de Parfum, 100 ml)
- Stilettos — https://officialmykonos.com/products/mykonos-stilettos-edp-50ml (Eau de Parfum, 50 ml)
- Untamed — https://officialmykonos.com/products/mykonos-untamed-extrait-de-parfum-100ml (Extrait de Parfum, 100 ml)
- Utopia — https://officialmykonos.com/products/mykonos-utopia-extrait-de-parfum-100ml (Extrait de Parfum, 100 ml)
- Vanilla Clouds — https://officialmykonos.com/products/mykonos-vanilla-clouds-extrait-de-parfum-50ml-1 (Extrait de Parfum, 50 ml)
- Verve — https://officialmykonos.com/products/mykonos-verve-extrait-de-parfum-when-in-paris-edp-50ml (official page title states Extrait de Parfum, 50 ml; the legacy URL slug is not used to override the displayed title)
- Xoxo Rosy — https://officialmykonos.com/products/mykonos-xoxo-rosy-edp-50ml (Eau de Parfum, 50 ml)
- MyEgo — https://officialmykonos.com/products/mykonos-x-alterego-myego-extrait-de-parfum-50ml-100ml (Extrait de Parfum, 50 ml and 100 ml)
- Empire x RRQ — https://officialmykonos.com/products/mykonos-x-rrq-empire-extrait-de-parfum-50ml-100ml (Extrait de Parfum, 50 ml and 100 ml)
- Glitch — https://officialmykonos.com/products/mykonos-x-setiawanade-glitch-extrait-de-parfum-50ml (Extrait de Parfum, 50 ml and 100 ml)
- Invade — https://officialmykonos.com/products/mykonos-x-setiawanade-invade-extrait-de-parfum-50ml (Extrait de Parfum, 50 ml)

The official “Slow Living” detail page explicitly distinguishes 50 ml Eau de Parfum from 100 ml Extrait de Parfum. Accordingly, concentration remains variant-specific and the product-level concentration is intentionally blank. The Senja and Verve pages have legacy URL slugs containing “edp” but their displayed official product titles say Extrait de Parfum; the catalog follows the title and product detail, not the URL slug.

All 23 existing identities are now marked `source_verified_name`, and their size-specific variant evidence URLs point to their individual product pages. Existing 15 ml travel-size selector variants are retained with their separate evidence and are not altered by this batch.

A regression test checks all 23 individual URLs, concentration handling, size-specific variant evidence and one canonical row per product. Combined with the first two batches, all 53 standalone perfume identities appearing across the current official 54-item all-products collection now have individual brand-owned product-page evidence. The 54th item is the generic Travel Size 15ML selector, not a separate canonical perfume identity. This conclusion is limited to the current official collection and does not prove exhaustive coverage of all historical, regional, or discontinued Mykonos fragrances.


### Gulf Orchid: official perfume collection detail-page reconciliation (9 November 2026)

The brand-owned Gulf Orchid Perfume collection was opened directly. Its current collection page distinguishes the Gulf Orchid brand from other brands also sold by the storefront, including Maison Asrar. The visible perfume collection includes standalone Gulf Orchid fragrances and two gift sets. The Sweet Edition and Flirt Edition bundles were excluded as separate canonical perfume identities.

Thirteen existing Gulf Orchid canonical identities were matched to individual brand-owned detail pages. Their existing product IDs were preserved and their identity status was upgraded to `source_verified_name`:

- Vanilla Addiction — https://shop-gulforchid.com/products/vanilla_addiction_eau_de_parfum — 100 ml Eau de Parfum
- Mango Ice — https://shop-gulforchid.com/products/mango_ice_eau_de_parfum — 100 ml Eau de Parfum
- Cotton Candy Musk — https://shop-gulforchid.com/products/gulf-orchid-musk-tahara-eau-de-parfum-cotton-candy — detail page confirms the name; size and concentration are not exposed in the inspected page content
- Tahara Vanilla Musk — https://shop-gulforchid.com/products/musk-eau-de-parfum-60-ml — detail page confirms the name; size and concentration are not exposed in the inspected page content, so the URL slug was not used as sole variant evidence
- Sweet Heaven 20ML — https://shop-gulforchid.com/products/sweet-heaven-by-gulf-orchid-eau-de-parfum-20ml — 20 ml Eau de Parfum
- Pink Marshmallow — https://shop-gulforchid.com/products/pink-marshmallow — 100 ml Eau de Parfum
- Coco Blanco — https://shop-gulforchid.com/products/coco-blanco — 100 ml Eau de Parfum
- Exotic Oud — https://shop-gulforchid.com/products/exotic_oud_eau_de_parfum — 100 ml Eau de Parfum
- Vanilla Latte — https://shop-gulforchid.com/products/vanilla_latte_eau_de_parfum — 100 ml Eau de Parfum
- Cookie Bite — https://shop-gulforchid.com/products/cookie-bite — 100 ml Eau de Parfum
- Sweet Like Candy — https://shop-gulforchid.com/products/sweet_like_candy_eau_de_parfum — 100 ml Eau de Parfum
- Sweet Heaven Extreme 20ML — https://shop-gulforchid.com/products/sweet-heaven-extreme-by-gulf-orchid-eau-de-parfum-20ml — 20 ml Eau de Parfum
- Piña Colada Musk — https://shop-gulforchid.com/products/gulf-orchid-musk-tahara-eau-de-parfum-pina-colada — 60 ml Eau de Parfum

Eleven size/concentration combinations were explicitly shown on their product detail pages and received one variant each, with matching `formats_ml`, concentration and `source_evidence_url`. Cotton Candy Musk and Tahara Vanilla Musk received no size or concentration fields and no variants because the inspected product-page body did not explicitly expose those attributes. No size was inferred from the Tahara URL slug alone.

The collection page also shows Sweet Edition and Flirt Edition gift sets; these were intentionally excluded from the fragrance identity count. This pass verifies the 13 current standalone Gulf Orchid products visible in the dedicated perfume collection, not the remaining legacy/regionally listed Gulf Orchid identities already present in the catalog. No prices, availability, or retailer offer data were copied.

Regression tests now cover all 13 individual product URLs, source status, explicit size/concentration variants, deliberate omissions for the two incomplete pages, and variant-ID uniqueness.


### Gulf Orchid / Maison Asrar: legacy multi-brand storefront attribution correction (9 November 2026)

A second review of the storefront's named collection pages found that the domain sells both Gulf Orchid and Maison Asrar fragrances. The collection filter and individual product-page brand label were used to correct ownership; the storefront domain alone is not treated as proof that every item is a Gulf Orchid product.

Three additional Gulf Orchid identities were verified from individual product pages and given explicit 100/110 ml Eau de Parfum variants:
- Al Qasr — https://shop-gulforchid.com/products/al-qasr-silver — 100 ml EDP
- Hikma — https://shop-gulforchid.com/products/hikma-by-gulf-orchid-eau-de-parfum — 110 ml EDP
- Riwaya — https://shop-gulforchid.com/products/riwaya_eau_de_parfum — 100 ml EDP

Several records previously filed under Gulf Orchid were corrected to Maison Asrar:
- **Asala:** the storefront's Asala collection lists an item named Asala under the Maison Asrar brand filter. Its old individual detail URL currently returns 404, so the existing identity is retained only at listing-level confidence, without size or concentration.
- **Turath:** the individual page https://shop-gulforchid.com/products/turath-eau-de-perfum-100ml explicitly identifies Maison Asrar, 100 ml EDP. It was reconciled into the already-existing Maison Asrar Turath identity, preserving the Maison Asrar product ID and adding one 100 ml EDP variant.
- **Vanilla Aura:** the individual page https://shop-gulforchid.com/products/vanilla-aura explicitly identifies Maison Asrar, 100 ml EDP. The Gulf Orchid duplicate row was removed; its source and 100 ml variant were merged into the existing Maison Asrar identity.
- **Vanilla Voyage:** the individual page https://shop-gulforchid.com/products/maison-asrar-vanilla-voyage-eau-de-parfum and its collection listing identify Maison Asrar. The Gulf Orchid duplicate row was removed and the official detail URL was applied to the existing Maison Asrar identity. The inspected detail page did not explicitly expose size/concentration, so no variant was added.

Three other imported labels were confirmed to be collection names rather than standalone perfume identities and removed from the canonical product list:
- **Hamsat** is a collection containing Hamsat Gharam, Hamsat Hob, Hamsat Ghazal and Hamsat Ishq; those individual Maison Asrar identities already exist.
- **Jawhara** is a collection containing Jawhara Rouge and Jawhara Black; those individual Maison Asrar identities already exist.
- **Jewel** is a collection containing Date Night, Red Velvet and Pink Crush (plus a bundle); those individual Maison Asrar identities already exist.

The removed collection-label rows had no variants and were not used as canonical perfume identities. The corresponding existing individual fragrances were preserved. Product IDs for retained records were preserved; the two duplicate Vanilla Aura / Vanilla Voyage rows were merged into their existing Maison Asrar canonical IDs. Regression tests now check these brand assignments, variant facts, duplicate prevention and exclusion of collection labels as products.


### Aromatix / French Avenue: official collection and product-page reconciliation (9 November 2026)

The official French Avenue storefront has a dedicated Aromatix Collection. Its current collection page shows ten standalone Aromatix fragrances plus two Aromatix Summer Vibes bundles. The bundles are sets and are not separate canonical perfume identities.

Ten existing catalog identities were matched to individual French Avenue product-detail pages. Nine pages explicitly state 100 ml and concentration; those received one 100 ml variant each. The tenth page, Plantine Blanc, confirms the product name but its inspected specifications section does not expose size or concentration, so no variant or concentration was inferred.

Verified detail-page identities:
- Carnal Desire — https://frenchavenue.com/products/carnal-desire — Eau de Parfum, 100 ml
- Forbidden Fruit — https://frenchavenue.com/products/aromatix-forbidden-fruit — Eau de Parfum, 100 ml
- Frostbite — https://frenchavenue.com/products/aromatix-frostbite — Extrait de Parfum, 100 ml
- Magnetiq — https://frenchavenue.com/products/aromatix-magnetiq — Eau de Parfum, 100 ml
- Naughty Dates — https://frenchavenue.com/products/aromatix-naughty-dates — Eau de Parfum, 100 ml
- Plantine Blanc — https://frenchavenue.com/products/aromatix-plantine-blanc — individual official page confirms identity; size/concentration not explicitly stated in the inspected page
- Royal Taboo — https://frenchavenue.com/products/royal-taboo — Extrait de Parfum, 100 ml
- Sun Kissed — https://frenchavenue.com/products/aromatix-sunkissed — Eau de Parfum, 100 ml
- Teas Me — https://frenchavenue.com/products/aromatix-teas-me — Eau de Parfum, 100 ml
- X Xandal — https://frenchavenue.com/products/aromatix-x-xandal — Extrait de Parfum, 100 ml

The official product title spells the name **Plantine Blanc**. The existing product ID was retained, the canonical spelling was corrected to Plantine Blanc, and the previous spelling Platine Blanc remains as an alias.

**Ora** and **Roza** remain at `source_listed_name` confidence using the existing Notino discovery listing. I did not find individual official French Avenue product pages for those two names in this pass, so their concentration and size remain unspecified and no variants were created. The official current collection page lists ten individual perfumes, while the existing catalog has twelve identities; this audit does not claim that Ora and Roza are discontinued or invalid.

Regression tests now check the ten official detail URLs, nine explicit 100 ml concentration variants, Plantine Blanc's deliberate missing variant data, and Ora/Roza's listing-only status.


### Maison Asrar: second new-arrivals page individual-detail reconciliation (9 November 2026)

The second page of Maison Asrar's official New Arrivals collection was opened and its 12 displayed perfume cards were matched against existing canonical identities. All 12 already existed; no new identities or variants were created in this pass. The existing product IDs were preserved and their product-level source URLs now point to the individual Maison Asrar detail pages:

- Dubai Milano — https://maisonasrar.com/products/dubai-milano
- Dubai London — https://maisonasrar.com/products/dubai-london
- Dubai Miami — https://maisonasrar.com/products/dubai-miami
- III Thriller — https://maisonasrar.com/products/iii-thriller
- Milky Way — https://maisonasrar.com/products/milky-way
- Vanguard — https://maisonasrar.com/products/vanguard
- Muharib — https://maisonasrar.com/products/muharib
- Faris Al Arab — https://maisonasrar.com/products/faris-al-arab
- Vanilla Seduction — https://maisonasrar.com/products/vanilla-seduction
- Vanilla Aura — https://maisonasrar.com/products/vanilla-aura
- Throne Eclipse — https://maisonasrar.com/products/throne-eclipse
- Throne — https://maisonasrar.com/products/throne

The inspected Maison Asrar detail pages confirm the individual product identities, but do not expose explicit size/concentration fields in their page content. Therefore no new variant data was inferred. Vanilla Aura retains its already documented 100 ml Eau de Parfum variant, whose evidence URL remains the Gulf Orchid storefront detail page that explicitly states those variant attributes; the Maison Asrar page is now the product-level identity source.

Regression coverage checks all 12 official URLs, source status, and the deliberate absence of unsupported variants.


### Maison Asrar: third new-arrivals page individual-detail reconciliation (9 November 2026)

The third page of the official Maison Asrar New Arrivals collection was opened. Its 12 perfume cards were matched to existing canonical identities, and all 12 now point to their individual Maison Asrar product pages with `source_verified_name` status:

- Khayyal — https://maisonasrar.com/products/khayyal
- Mohra — https://maisonasrar.com/products/mohrab
- Hikaya — https://maisonasrar.com/products/hikaya
- Hilm — https://maisonasrar.com/products/hilm
- Cascade — https://maisonasrar.com/products/cascade
- Tornado — https://maisonasrar.com/products/tornado
- Wadi — https://maisonasrar.com/products/wadi
- DXB — https://maisonasrar.com/products/dxb
- Legacy — https://maisonasrar.com/products/legacy
- Vanilla Voyage — https://maisonasrar.com/products/vanilla-voyage-eau-de-parfum
- Vision — https://maisonasrar.com/products/vision
- Oh Honey! — https://maisonasrar.com/products/oh-honey-eau-de-parfum

These individual detail pages confirm the product identities, but the inspected page content did not explicitly expose size/concentration. No variants or concentration fields were inferred. Existing product IDs and variant counts are unchanged. Vanilla Voyage's previous retailer-backed identity URL was replaced by the brand's own product page; it still has no variant because no size was explicitly confirmed in the inspected page.

Regression coverage checks the 12 official URLs and ensures no unsupported sizes or concentrations are introduced.
