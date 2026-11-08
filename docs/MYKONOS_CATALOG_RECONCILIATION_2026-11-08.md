# Mykonos catalogue reconciliation — 2026-11-08

## Scope and source hierarchy

This review compares the existing ScentHunter Mykonos seed with:
- Fragrantica designer page: https://www.fragrantica.com/designers/Mykonos.html (84 listed fragrance records at the time of review).
- Mykonos official Indonesian storefront: https://officialmykonos.com/collections/all and product detail pages.
- Mykonos EU's catalogue explorer: https://mykonosperfumes.eu/pages/explore. This retailer explicitly states that it is **not** the official Mykonos website, but an authorized European retailer. Its explorer currently labels the range as 89 fragrances and provides individual pages for current and announced products.

The counts are not directly interchangeable. Fragrantica has collection groupings and a separate Body Mists category. The EU retailer includes announced/coming-soon products and its list does not include every legacy/other-market item (notably Imperium, which is present on Mykonos's Indonesian storefront and Fragrantica). Do not claim that one number is the definitive worldwide active range.

## Seed reconciliation

Before this update, the Mykonos seed on the PR base branch contained 72 canonical identities. The reconciled branch contains 99 identities: a net addition of 27, with no Mykonos identities removed. The 18 brand-owned 15 ml travel-size variants already present on the base branch are preserved; they are not inferred from parent bottle sizes. These additions are a cross-source union from the authorized EU retailer's product pages and new-release explorer, the official Indonesian storefront, and Fragrantica's indexed designer listing. They include current EU-range names, separately documented announced products, and eight name-only legacy entries. The final branch contains 102 explicit variants: 91 carried forward from the base branch (including the 18 explicitly selectable 15 ml travel sizes) plus 11 newly evidenced variants. The 99 count is not a claim that all products are simultaneously available for purchase, and the source counts are not interchangeable. The 27 net additions are: Adelina, Avra Kehdabra, Berry Caramel Pancake, Bloody Mary, Café Lyon, Celestial, Crystals, Daydream, Dolce Cherry, Déjà Vu, Eclipse, Elysian, Forever Musc, Inception Reimagined, Inspire Perfume, It's Not Ella, Kingsman, Monaco Royale Black, Nashi Pear Garden, President, Roulette, Shape Shift, Soft Hour x NCT Haechan, Undercover, Violette, Wallflower and Zeus.

## Added identities

| Name | Source page | Variant treatment |
|---|---|---|
| Forever Musc | https://mykonosperfumes.eu/products/mykonos-forever-musc | 100 ml Eau de Parfum confirmed |
| Inspire Perfume | https://mykonosperfumes.eu/products/mykonos-inspire | Name and 100 ml bottle listed; concentration not stated, no variant created |
| Daydream | https://mykonosperfumes.eu/products/mykonos-daydream | 100 ml Extrait de Parfum; coming soon |
| Inception Reimagined | https://mykonosperfumes.eu/products/mykonos-inception-reimagined | 100 ml Extrait de Parfum; coming soon |
| Monaco Royale Black | https://mykonosperfumes.eu/products/mykonos-monaco-royale-black | 50 ml and 100 ml Extrait de Parfum; coming soon |
| Shape Shift | https://mykonosperfumes.eu/products/mykonos-shape-shift | 100 ml Extrait de Parfum; coming soon |
| Kingsman | https://mykonosperfumes.eu/products/mykonos-kingsman | Name listed; size/concentration not confirmed at launch, no variant created |
| Wallflower | https://mykonosperfumes.eu/products/mykonos-wallflower | Name listed; size/concentration not confirmed at launch, no variant created |
| Elysian | https://mykonosperfumes.eu/products/mykonos-elysian | Name listed; size/concentration not confirmed at launch, no variant created |
| Undercover | https://mykonosperfumes.eu/products/mykonos-undercover | Name listed; size/concentration not confirmed at launch, no variant created |
| Celestial | https://mykonosperfumes.eu/products/mykonos-celestial | Name listed; size/concentration not confirmed at launch, no variant created |
| Café Lyon | https://mykonosperfumes.eu/products/mykonos-cafe-lyon | Name listed; size/concentration not confirmed at launch, no variant created |
| President | https://mykonosperfumes.eu/products/mykonos-president | Name listed; size/concentration not confirmed at launch, no variant created |
| Déjà Vu | https://mykonosperfumes.eu/products/mykonos-deja-vu | Name listed; size/concentration not confirmed at launch, no variant created |
| Soft Hour x NCT Haechan | https://mykonosperfumes.eu/products/mykonos-x-nct-haechan-soft-hour | 100 ml Extrait de Parfum confirmed; coming soon |

## Reconciliation flags — do not create duplicate products

- Fragrantica spells Jynx as “Jinx”; the retailer's product page confirms “Jynx”. Treat as a spelling alias pending official confirmation, not a second fragrance.
- Fragrantica spells Nautilus as “Nautilius” in one result listing. The official Indonesian storefront and EU retailer use “Nautilus”. Treat “Nautilius” as a source spelling alias, not a second product.
- Fragrantica has both “California” and “California Signature”; the Indonesian official product page uses the product title “California” but the description calls it “California Signature”. ScentHunter's existing California record points to that product page. Keep one record for now and flag the naming/identity for manual confirmation rather than duplicating it.
- Fragrantica's “Empire” appears to correspond to the collaboration product “Empire x RRQ”; preserve the collaboration identity and add an alias only if the official product page supports it.
- Fragrantica's “Shades Parfum”/“Shades Perfume” wording should be normalized as an alias after checking the official product page.
- The separate Body Mists collection on Fragrantica must not be imported into the perfume product set as Extrait/EDP variants. Body mists, hair mists, and similar formats need their own product-type handling if ScentHunter chooses to cover them.

## Validation and limits

- The catalog and family registry are updated with 15 new canonical identities.
- Variants are created only where the retailer page states concentration and size: Daydream, Inception Reimagined, Monaco Royale Black (50/100 ml), Shape Shift, Forever Musc, and Soft Hour x NCT Haechan.
- No size/concentration variants are created for Inspire Perfume or the announced names whose page says the final concentration/size is not confirmed.
- Fragrantica currently reports 84 records; its page could not be opened directly by the crawler (403), so its indexed designer listing is used for name-level cross-check only.
- This is a cross-source reconciliation snapshot, not a guarantee of worldwide historical completeness or current stock availability.

## Fragrantica-only legacy / additional names

The indexed Fragrantica designer page's All Fragrances and collection sections include additional perfume names not present in the current 89-item EU retailer A–Z perfume list or the current official Indonesian 54-product collection. These have been added as name-only records with Fragrantica as the evidence URL; no sizes, concentrations or variants are inferred:
- Adelina
- Bloody Mary
- Crystals
- Eclipse
- Nashi Pear Garden
- Roulette
- Zeus
- It's Not Ella

This brings the cross-source union in ScentHunter to 98 Mykonos perfume identities. It is intentionally not called “84 Fragrantica perfumes”: Fragrantica's designer count includes overlapping collection groupings, while the union also includes EU retailer announcements and the Indonesian official catalog's Imperium.

### Alias reconciliation

The following source spellings/names are aliases on existing identities, not extra products:
- Jinx → Jynx
- Nautilius → Nautilus
- XoXo, Rosy → Xoxo Rosy
- Empire → Empire x RRQ
- California Signature → California (official Indonesian product page title is California; its description calls it California Signature)
- Shades Parfum → Shades Perfume
- Intimate Affair → Affair (retailer/secondary catalogue wording; retain as alias pending a dedicated official product-page check)

The three items in Fragrantica's separate Body Mists section — Love, Rosy; Lychee Breeze; Matcha Sundays — are deliberately not added as perfume identities. They require a separate product-type taxonomy and should not be treated as Extrait/EDP variants.
