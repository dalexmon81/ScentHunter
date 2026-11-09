

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
