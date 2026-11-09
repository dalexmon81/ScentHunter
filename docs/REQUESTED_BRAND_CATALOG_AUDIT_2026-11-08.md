

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


### Al Haramain: five additional official New Launches detail pages (9 November 2026)

The official EU New Launches collection (63 entries) was reconciled against the existing 101 Al Haramain identities. Five distinct fragrance identities absent from the seed were verified on individual product-detail pages:

- Haramain Camellia — https://shop.alharamainperfumes.com/eu/haramain-camellia.html
- Amber Oud Smell Dubai — https://shop.alharamainperfumes.com/eu/haramain-amber-oud-smell-dubai-100ml-extrait-de-parfum.html
- Sameera — https://shop.alharamainperfumes.com/eu/haramain-sameera-100ml-extrait-de-parfum.html
- Empire Aromatique Ombre — https://shop.alharamainperfumes.com/eu/haramain-empire-aromatique-ombre-100ml-extrait-de-parfum.html
- Leif — https://shop.alharamainperfumes.com/eu/haramain-leif-100ml-eau-de-parfum.html

Four detail pages explicitly state 100 ml and concentration; one 100 ml variant was added for each. Camellia's individual page confirms the perfume and Extrait de Parfum concentration but does not state a bottle size, so no size or variant was inferred. Other entries in the 63-item collection include bukhoor tablets and 30 ml × 12 multipacks; these were not treated as individual perfume identities. Ayaat Malika Gold was not promoted because the product title says Extrait de Parfum while its detail metadata says Eau de Parfum. Sameera Noir and Olaf remain leads until their individual pages can be independently checked.

This update adds five canonical identities and four explicit variants. All rows retain first-party product-detail URLs. No prices, stock, or retailer offers were copied into the canonical seed.

### Al Haramain: two further verified product-detail pages (9 November 2026)

Two additional identities absent from the current 106-product Al Haramain catalog were checked against individual first-party detail pages and added with explicit 100 ml variants:

- Sameera Noir — https://us.alharamainperfumes.com/en/haramain-sameera-noir-100ml-extrait-de-parfum.html (100 ml, Extrait de Parfum; SKU AHP2005)
- Olaf — https://shop.alharamainperfumes.com/eu/haramain-olaf-100ml-eau-de-parfum.html (100 ml, Eau de Parfum; SKU AHP2090)

Sameera Noir's EU listing is visible in the official 63-item New Launches collection, while its individual verified product detail was accessible on Al Haramain's official US store. Olaf's EU detail page explicitly confirms 100 ml and Eau de Parfum. No prices, stock, or retailer offers were copied into the catalog.

### Khadlaj: two additional verified perfume sprays (9 November 2026)

- Muse — https://khadlaj-perfumes.com/products/khadlaj-muse-100-ml-eau-de-parfum-spray-for-women — official product detail identifies a 100 ml Eau de Parfum spray (SKU 6298043072748).
- Onyx Galaxy — https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-onyx-galaxy-100-ml-eau-de-parfum-for-men — official product detail identifies a 100 ml Eau de Parfum spray (SKU 6298043072762).

Both names were already present as listing-level identities; their records were upgraded using individual first-party detail pages and each received one explicitly evidenced 100 ml variant. No retailer price or availability data was imported.
