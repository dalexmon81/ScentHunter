

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


### Maison Asrar: first-party identity and variant audit (8 November 2026)

#### Identity coverage

- Current seed: **120 canonical identities**, with no duplicate `product_id` and no duplicate canonical name.
- The brand-owned `/collections/perfume-sprays` collection reports **74 products** across its seven paginated pages. All 74 names were compared with the seed; all 74 are already present.
- An independent European guide reports 116 Maison Asrar fragrances. Its complete 116-name list was compared with the seed: all 116 names are present. The four additional seed names are **Black Grapefruit**, **Plot Twist**, **Love Key** and **Unsolved Mystery**.
- Black Grapefruit appears in the brand-owned perfume collection. Plot Twist, Love Key and Unsolved Mystery are presented as **Maison Asrar** products on Gulf Orchid's store and product pages, not as Gulf Orchid-branded fragrances. Their product pages explicitly state 100 ml EDP and the seed already contains their three matching variants.

The independent guide explicitly states that it is not the official Maison Asrar site and is operated by FragranceGems, an independent retailer. Its 116-name list is a useful secondary coverage cross-check, not first-party proof. It says it uses the brand's notes where published and takes size/type from brand pages, store labels or store product data. Its size data includes multiple sizes (25, 80, 90, 100 and 110 ml), so it must not be flattened into a global 100 ml default.

#### First-party variant evidence added in this PR

Two brand-owned product URLs explicitly include both concentration and size in the product slug:

| Product | Brand-owned product URL | Confirmed variant |
|---|---|---|
| Treasure | https://maisonasrar.com/products/maison-asrar-treasure-eau-de-parfum-100-ml-unisex | 100 ml Eau de Parfum |
| Heritage | https://maisonasrar.com/products/maison-asrar-heritage-eau-de-parfum-100-ml-unisex | 100 ml Eau de Parfum |

The seed now records `formats_ml: [100]` and one explicit variant row for each of these two identities. Existing first-party pages for Imperial and Monarch identify Eau de Parfum in their product URLs but do not state a size; no size was inferred for them. The inspected Belgravia, Legacy, Vanguard, Regent and Majesty pages do not expose an explicit size or concentration in their visible product details, so no variants were invented for those products.

#### Remaining data-quality gaps

- Current Maison Asrar variant rows after this change: **5** (Plot Twist, Love Key, Unsolved Mystery, Treasure, Heritage).
- **115 of 120** identities still have no explicit variant row or `formats_ml` value.
- Only four product records currently state concentration at product level: Treasure, Imperial, Monarch and Heritage. The three Gulf Orchid-sold Maison Asrar products express concentration on their variant rows.
- 12 records have product-specific source URLs (9 on `maisonasrar.com`, 3 on the Gulf Orchid store); 108 still point to the generic Maison Asrar collection page. Individual first-party source URL coverage therefore remains a separate cleanup task.

**Catalog decision:** add only the two 100 ml EDP variants supported by brand-owned product URLs. Do not fill the remaining 115 identities with 100 ml variants from the independent guide or apply a universal concentration/size assumption. Keep the three Gulf Orchid-sold fragrances assigned to Maison Asrar because their product pages explicitly identify Maison Asrar as the brand. Do not mark the other seed identities discontinued merely because they are absent from the 74-product `perfume-sprays` collection; the brand also exposes separate product collections and individual product pages.

First-party references:
- Brand fragrance collection: https://maisonasrar.com/collections/perfume-sprays
- Treasure: https://maisonasrar.com/products/maison-asrar-treasure-eau-de-parfum-100-ml-unisex
- Heritage: https://maisonasrar.com/products/maison-asrar-heritage-eau-de-parfum-100-ml-unisex
- Imperial: https://maisonasrar.com/products/maison-asrar-imperial-eau-de-parfum
- Monarch: https://maisonasrar.com/products/maison-asrar-monarch-eau-de-parfum
- Gulf Orchid product pages: https://shop-gulforchid.com/products/plot-twist ; https://shop-gulforchid.com/products/love-key ; https://shop-gulforchid.com/products/unsolved-mystery
- Independent cross-check (not official): https://maisonasrarperfumes.eu/fr/perfumes/


### Khadlaj: official perfume-spray coverage and variant reconciliation (8 November 2026)

#### Identity coverage

- Seed before this pass: **116 Khadlaj identities / 29 variants**.
- The brand-owned `https://khadlaj-perfumes.com/collections/perfumes-spray` collection reports **101 products**. Eight paginated pages exposed **96 individual product cards** with readable names and product-image labels. The linked ninth page returned no product cards, so five of the 101 reported items remain unidentified in this pass.
- All 96 visible official product names map to existing seed identities after alias reconciliation. No new canonical identity was required from the 96 visible cards.
- The official card spelling `SENSUOS NIGHT` / product-page slug `sensous-night` maps to the seed's `Sensuous Night`; the aliases now include `Sensuos Night` and `Sensous Night`. Do not create a second identity.
- `WILD INDONESIAN OUD PURE` maps to the seed identity `Wild Indonesian Oud` through its existing alias. Do not create a duplicate.
- `KHADLAJ 25 EXPERIENCE/TRUST/LOYALTY/HERITAGE/INTEGRITY` map to the seed's shorter canonical names `25 Experience`, `25 Trust`, `25 Loyalty`, `25 Heritage` and `25 Integrity`; their aliases preserve the official full names.
- `Hareem Al Sultan` (75 ml EDP spray) is a separate identity from `Hareem Al Sultan Gold` (35 ml product). Both are retained.

#### First-party variants added

The official collection cards and linked product pages explicitly state sizes and concentrations for the 96 visible products. Eighteen of those products already had matching variant rows. This PR adds the **78 missing variant rows**, bringing the visible official range to 96 products with explicit variant rows. The brand's total in the seed becomes **116 identities / 107 variants**; the other 11 existing variants, which belong to identities outside these 96 visible cards, are preserved.

The newly recorded variants cover the actual sizes shown by the brand: 60 ml, 75 ml, 85 ml and 100 ml. No blanket 100 ml default was applied. The product-level `formats_ml` and concentration fields were updated to match the first-party evidence where stated. For products with a known size but conflicting concentration text, size is recorded while concentration is left blank.

**Source inconsistency:** the official Saqr Al Badiya product page's image/URL labels it Extrait de Parfum, while the body description calls it Eau de Parfum. The variant is therefore recorded as 100 ml with concentration unconfirmed; neither concentration is selected by guesswork.

The following direct product pages were checked and recorded as product-specific evidence:
- Panache Angel Dust: https://khadlaj-perfumes.com/collections/perfumes-spray/products/panache-angel-dust-100-ml-extrait-de-parfum-spray-for-women-shop-online-dubai-uae
- Oud Pure Oud Barakat: https://khadlaj-perfumes.com/collections/perfumes-spray/products/oud-pure-oud-barakat-60-ml-master-perfumer-collection-edp-spray-for-men-women
- Nuha Bon Bon: https://khadlaj-perfumes.com/collections/perfumes-spray/products/nuha-bon-bon-strawberry-vanilla-ice-cream-gourmand-perfume-for-women-online
- Hareem Al Sultan: https://khadlaj-perfumes.com/collections/perfumes-spray/products/tiktk-viral-hareem-al-sultan-perfume-in-75-ml-edp-spray-by-khadlaj-dubai
- Saqr Al Badiya: https://khadlaj-perfumes.com/collections/perfumes-spray/products/saqr-al-badiya-extrait-de-parfum-spray-for-men-with-aquatic-notes-shop-online-dubai-uae
- Wild Indonesian Oud Pure: https://khadlaj-perfumes.com/collections/perfumes-spray/products/wild-indonesian-oud-spray-shop-online-best-price-in-dubai-uae
- Sensuos Night: https://khadlaj-perfumes.com/collections/perfumes-spray/products/sensous-night-edp-spray-shop-online-best-price-in-dubai-uae
- La Fede Celebrity Fame: https://khadlaj-perfumes.com/collections/perfumes-spray/products/la-fede-celebrity-fame-100ml-eau-de-parfum
- Ihthiraam: https://khadlaj-perfumes.com/collections/perfumes-spray/products/ihthraam-extrait-de-parfum-spray-oriental-unisex-fragrance
- Khadlaj 25 Experience: https://khadlaj-perfumes.com/collections/perfumes-spray/products/khadlaj-25-experience-100-ml-edp-spray
- Khadlaj 25 Trust: https://khadlaj-perfumes.com/collections/perfumes-spray/products/buy-khadlaj-25-trust-100-ml-edp-spray-best-gourmand-perfume-for-women
- Khadlaj 25 Loyalty: https://khadlaj-perfumes.com/collections/perfumes-spray/products/khadlaj-25-loyalty-100-ml-edp-spray-best-women-perfume-to-shop-online-dubai-uae
- Khadlaj 25 Heritage: https://khadlaj-perfumes.com/collections/perfumes-spray/products/khadlaj-25-heritage-100-ml-edp-spray
- Khadlaj 25 Integrity: https://khadlaj-perfumes.com/collections/perfumes-spray/products/khadlaj-25-integrity-100-ml-edp-spray

The 96 collection-card records are linked to their corresponding official listing pages 1–8; each card's image alt text carries the size/concentration label. The collection count of 101 is retained as the source-reported total, but the five records not exposed by page 9 remain a discovery gap. Do not infer their names or variants.

#### Validation and remaining work

- Full catalog after this branch: **2,061 identities / 353 variants**.
- Khadlaj: **116 identities / 107 variants**; 9 Khadlaj identities still have no variant row and remain outside the 96 visible official product cards.
- No duplicate product IDs, duplicate brand/canonical names, duplicate variant IDs, orphan variants or variant-size mismatches were found.
- The 9 remaining identities are not deleted or marked discontinued; they may be legacy, regional or present in other Khadlaj collections. The five product cards not surfaced by the official page-9 response also remain unresolved.

First-party collection pages:
- Page 1: https://khadlaj-perfumes.com/collections/perfumes-spray
- Page 2: https://khadlaj-perfumes.com/collections/perfumes-spray?page=2
- Page 3: https://khadlaj-perfumes.com/collections/perfumes-spray?page=3
- Page 4: https://khadlaj-perfumes.com/collections/perfumes-spray?page=4
- Page 5: https://khadlaj-perfumes.com/collections/perfumes-spray?page=5
- Page 6: https://khadlaj-perfumes.com/collections/perfumes-spray?page=6
- Page 7: https://khadlaj-perfumes.com/collections/perfumes-spray?page=7
- Page 8: https://khadlaj-perfumes.com/collections/perfumes-spray?page=8
- Page 9 (reported count only; no product cards returned): https://khadlaj-perfumes.com/collections/perfumes-spray?page=9


CI note: the catalog validation workflow now explicitly includes the stacked target branch `catalog/maison-asrar-verified-variants-2026-11-08`; this PR head was advanced after the base-branch trigger update so the pull-request validation can run without changing `main`.


### Khadlaj follow-up: last nine seeded identities receive first-party variants (8 November 2026)

The nine Khadlaj identities that still lacked a variant after the first collection pass were checked against additional brand-owned product pages and official new-launch collections. All nine now have an explicit first-party size/concentration variant:

| Identity | Official product page | Variant |
|---|---|---|
| Panache Eleganza | https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/panache-eleganza-100-ml-extrait-de-parfum-spray-for-women | 100 ml Extrait de Parfum |
| Stellar Musk | https://khadlaj-perfumes.com/collections/women-perfume/products/stellar-musk-100-ml-edp-spray-for-women | 100 ml Eau de Parfum |
| Stellar Oud | https://khadlaj-perfumes.com/products/stellar-oud-100-ml-edp-spray-for-men-women | 100 ml Eau de Parfum |
| Onyx Galaxy | https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-onyx-galaxy-100-ml-eau-de-parfum-for-men | 100 ml Eau de Parfum |
| Muse | https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-muse-100-ml-eau-de-parfum-spray-for-women | 100 ml Eau de Parfum |
| Sueno | https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/sueno-100ml-extrait-de-parfum-for-women | 100 ml Extrait de Parfum |
| Saraya | https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-saraya-60-ml-extrait-de-parfum-spray-for-men-women | 60 ml Extrait de Parfum |
| Zayaan Silver | https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/zayaan-silver-fresh-aquatic-spicy-woody-eau-de-parfum-for-men | 100 ml Eau de Parfum |
| Qarar | https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-qarar-unisex-bold-oriental-extrait-de-parfum | 60 ml Extrait de Parfum |

**Updated Khadlaj result:** 116 canonical identities / 116 explicit variant rows. No Khadlaj identity in the current seed remains without a variant. The five product cards not surfaced by the ninth page of the 101-item Perfume Sprays collection remain a source-discovery limitation; the nine records above were found through separate official product/new-launch pages, not guessed from the missing cards.

**Updated whole-catalog result on this branch:** 2,061 product identities / 362 variants. Integrity checks report zero duplicate product IDs, duplicate brand/canonical-name pairs, duplicate variant IDs, orphan variants or variant-size mismatches. The full GitHub Actions catalog validation passed on commit `ae6e83b1f08973feef8190a3c9cd4e81864ad7d7` (run 42472046924). The subsequent audit-only update does not alter catalog data.


### Bujairami: UAE and Australian Originals coverage audit (8 November 2026)

#### UAE current assortment

- Seed before this pass: **142 Bujairami identities / 2 variants**.
- The brand-owned UAE `bujairami.ae/collections/all` collection reports 117 products. Its four visible pages (1–4) were compared with the seed: **all 117 names are already present**. No UAE identity was added or removed in this pass.

#### Australian Originals assortment

- The Bujairami-global `bujairami.com.au/collections/originals` collection reports 40 product entries. This resolves to **39 distinct names** because Love Spell is listed twice as separate 50 ml and 100 ml product pages. One of the 39 names is `Almura Body Spray`, which is not a perfume and remains excluded. The perfume scope is therefore **38 unique fragrances**.
- Before this pass, 28 of those 38 perfume identities were already in the seed; the ten missing official product identities were added with direct brand-owned product pages:
  - Sasha — https://bujairami.com.au/products/sasha-original-creation
  - Iconic — https://bujairami.com.au/products/iconic-by-bujairami
  - Australian Tonka — https://bujairami.com.au/products/australian-tonka-original-creation
  - Happy Hour — https://bujairami.com.au/products/happy-hour-inspired-by-mango-mood-phlur
  - Boujee Oud — https://bujairami.com.au/products/sexy-oud-original-creation-extrait
  - Mousse Cake — https://bujairami.com.au/products/mousse-cake-original-creation
  - No.1 Father — https://bujairami.com.au/products/no-1-father-original-creation
  - Pretty F**ked Up — https://bujairami.com.au/products/pretty-f-ked-up-original-creation-50ml
  - Vicious — https://bujairami.com.au/products/vicious-inspired-by-dirty-heaven-borntostandout
  - Sunset Bay — https://bujairami.com.au/products/sunset-bay-inspired-by-cap-camarat-memo-paris
- The seed now contains **152 identities**. The family registry was updated with the ten matching discovery records.

#### First-party size/concentration evidence

- Five new variant rows were added: Iconic 100 ml, Australian Tonka 100 ml, Happy Hour 100 ml, Pretty F**ked Up 50 ml and The F**ck Up 50 ml. The Love Spell 50 ml and 100 ml variants already existed; their variant source URLs were upgraded to the two direct product pages:
  - https://bujairami.com.au/products/love-spell-original-creation-50ml
  - https://bujairami.com.au/products/love-spell-original-creation
- Boujee Oud is explicitly described as Extrait de Parfum, but its page does not state a size; concentration is recorded without inventing a size.
- Sasha, Mousse Cake, No.1 Father, Vicious and Sunset Bay have product pages but no explicit size/concentration in the inspected visible details. They remain identity-only.
- The body spray `Almura Body Spray` remains excluded from the perfume catalog.
- Current Bujairami seed: **152 identities / 7 variants**. This is not a complete variant audit of the 152 products; sizes/concentrations for the 117 UAE products and many existing Australian products still need first-party product-page checks.

#### Separate global Inspired range: scope not yet approved

- The official Australian `bujairami.com.au/collections/inspired` collection reports **1,175 product entries**. This is a much larger regional range than the UAE collection and should not be treated as 1,175 unique canonical fragrances without deduplication; the listings may include separate sizes, versions and inspired products.
- The first 64 visible product cards were compared against the current seed. **31 names did not match an existing canonical name or alias** in this first-page sample:
  `Breezy`, `Glorious`, `Ripper`, `Madness Extreme`, `Tip-Top`, `Woody Oud`, `Shortcake`, `Lavish`, `The Hype`, `Lavish Life`, `Vanacco`, `I have Money`, `Million Dollar Smell`, `Night Out`, `Top Notch`, `Casanova XJ 1861`, `Shu Helou`, `Rush Hour`, `Party Monster`, `Drip`, `Halo`, `Greatness`, `Young OG`, `Right One`, `Bahebak`, `Carnival`, `Soprano`, `InstaSmash`, `Bad N Boujee`, `Astro`, `Booz`.
- These are discovery leads only. Some may be separate inspired fragrances; others may be naming differences from existing products (for example, `Drip` vs `Drip No. 7`, or `Booz` vs `Booz Extreme`). No automatic merges or additions were made from the first-page sample.

**Scope decision required before the next Bujairami expansion:** include the entire Australian Inspired collection (1,175 product entries, requiring deduplication and regional/size reconciliation), or limit the canonical brand range to the 117-product UAE collection plus the Australian Originals collection. The existing seed already mixes both regional sources, so this needs an explicit and consistent rule before a much larger ingestion.

First-party collection references:
- UAE collection: https://bujairami.ae/collections/all
- Australian Originals: https://bujairami.com.au/collections/originals
- Australian Inspired: https://bujairami.com.au/collections/inspired
