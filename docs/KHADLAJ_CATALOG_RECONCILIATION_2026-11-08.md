# Khadlaj catalog reconciliation — 2026-11-08

## Result

The reconciled catalog contains **233 canonical Khadlaj fragrance identities and 226 explicit size variants**. These are a cross-source catalog snapshot, not a claim that every item is currently in stock or sold in every market.

The product identities are deduplicated across official Khadlaj pages, official collection listings and Fragrantica discovery. The 147 names in the Fragrantica designer index are covered by canonical names or aliases. Name-only records remain name-only where no bottle size or concentration is established.

## Catalog lines

- **La Fede:** 42 canonical identities, including individually sourced product pages and Code Viola Nectar.
- **Official perfume-spray range:** 61 product records in the dedicated spray family; the family registry contains 69 distinct names after collapsing the “Musk Pure Musk Blend Creation of Iqbal” alias.
- **Shiyaaka:** 8 distinct products.
- **Official perfume oils:** 48 canonical names reconciled from the official collection pages.
- **Dehn Al Oud:** 9 products, including the 3 ml oils and Rooh Al Oud.
- **Fragrantica oil discovery:** 36 name-level candidates retained separately from the official oil collection. They are not automatically treated as current stock or given guessed variants.

The 233 count includes these lines and the remaining Khadlaj catalog identities. Each canonical product appears once in product_catalog.json.

## Variant and source rules

Every one of the 226 Khadlaj variant records has a source_evidence_url. Official product pages are preferred; official collection pages are used where the listing itself is the available evidence. Product size and concentration are kept separate from canonical identity.

Official oil sizes are normalized to the concentration label “Perfume Oil”. The official oil collection records 12 ml, 15 ml, 17 ml, 18 ml, 20 ml, 25 ml, 27 ml, 30 ml and 35 ml formats.

## Identity and source corrections

- **Alf Wardat** is retained as an alias of **Alf Wardaat**.
- **Rose & Romance** is retained as an alias of **Rose And Romance**.
- **Musk Pure Musk Blend Creation of Iqbal** is retained as an alias of **Musk Pure Musk Blend**, not a second canonical identity.
- **La Fede Celeste Fluer**, **Sensuos Night**, **Sensous Night**, **Sueño** and **Shiyaaka Men** are handled as spelling/display aliases where applicable.
- **Rasayel Vid:** the official detail page confirms 100 ml Eau de Parfum despite “Extrait” in the URL slug.
- **Saqr Al Badiya:** 100 ml is confirmed, but concentration is deliberately left blank. The official page's title/images and descriptive text conflict on EDP versus Extrait.
- **Mukhallath Ma'a Ward Taiba:** the official product detail confirms 12 ml.

## Sources reviewed

- Official Khadlaj perfume spray collection: https://khadlaj-perfumes.com/collections/perfumes-spray
- Official Khadlaj perfume oil collection: https://khadlaj-perfumes.com/collections/perfume-oils
- Official concentrated perfume oils collection: https://khadlaj-perfumes.com/collections/concentrated-perfume-oils
- Official Dehn Al Oud collection: https://khadlaj-perfumes.com/collections/dehn-al-oudh
- Official La Fede collection: https://khadlaj-perfumes.com/collections/new-launch-la-fede-eau-de-parfum-collection-by-khadlaj-perfumes
- Fragrantica designer index: https://www.fragrantica.com/designers/Khadlaj.html

## Scope limits

The official storefront uses several overlapping perfume-oil collections and their displayed counts differ. The catalog keeps the 48-name official oil collection separate from the 36-name Fragrantica oil-discovery family and the 9-product Dehn Al Oud range. This avoids treating different collection counts as interchangeable or implying current availability.
