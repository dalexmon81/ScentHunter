# Maison Asrar catalog reconciliation — 8 November 2026

## Source hierarchy and current counts

The brand-owned storefront is the primary source:
- All products: https://maisonasrar.com/collections/all
- Fragrances: https://maisonasrar.com/collections/perfume-sprays
- Collections: https://maisonasrar.com/collections

At the time of this audit, the official all-products collection displayed 130 products, while the dedicated Fragrances collection displayed 74 product cards across seven pages. The final page repeats Belgravia, so the visible fragrance collection contains 73 distinct names. The storefront separately labels Room Spray and Home Fragrances in its navigation. Therefore the 130-item all-products count must not be interpreted as 130 perfumes.

An independent EU reseller's guide lists 116 scents and explicitly states that it is not the official Maison Asrar website. It is useful as a discovery and historical cross-check, but it is not treated as primary proof of brand ownership or a substitute for official product pages:
https://maisonasrarperfumes.eu/perfumes/

## Catalog snapshot

The working catalog snapshot contains:
- 120 Maison Asrar canonical identities.
- 9 identities already supported by Maison Asrar-owned individual product pages before the previous evidence passes, plus 3 Lock & Key identities explicitly branded Maison Asrar on Gulf Orchid's storefront.
- 61 identities still lacking individual product-page evidence after these passes.
- 3 additional Maison Asrar records — Plot Twist, Love Key and Unsolved Mystery — are listed on Gulf Orchid's own storefront. Their individual product pages explicitly label the brand as Maison Asrar and state 100 ml EDP. They are retained as Maison Asrar identities, and their existing variants now carry the corresponding page-level evidence URL. Gulf Orchid is the storefront/source for these Lock & Key releases; the records are not reassigned to Gulf Orchid as the fragrance brand.

The 120 identities should not be described as a verified, complete current range. The three Lock & Key records are separately supported by Gulf Orchid product pages that explicitly identify Maison Asrar as the fragrance brand; they are not counted among the 44 Maison Asrar-owned product-page records. The 74 official fragrance collection count is a current storefront snapshot; it does not establish that older or discontinued identities are invalid.

## Official detail-page upgrades in this change

Forty-seven existing identities were upgraded to individual Maison Asrar product pages in this PR, across three evidence passes:
- Bloom Bloom — 100 ml Eau de Parfum
- Lolita — 100 ml Eau de Parfum
- Bonita — 100 ml Eau de Parfum
- Lily — 100 ml Eau de Parfum
- Kiss My Lips — 90 ml Eau de Parfum
- Never Forget Me — 90 ml Eau de Parfum
- Night in Paris — 90 ml Eau de Parfum
- Sunset in Capri — 90 ml Eau de Parfum
- Dear Jasmine — 100 ml Eau de Parfum
- Patchouli with Love — 100 ml Eau de Parfum
- Fresh Iris — 100 ml Eau de Parfum
- Vanilla Rouge — 100 ml Eau de Parfum
- Jawhara Rouge
- Jawhara Black
- Petra
- Casablanca
- Trophy
- Oscar
- Fairy Tale
- Magic Night
- Icon
- Desire
- Black
- 1963
- Emessa
- Zenobia
- Fakhama
- Hamsat Ishq
- Hamsat Ghazal
- Hamsat Hob
- Hamsat Gharam
- Pink Crush
- Red Velvet
- Adorable
- Ameer
- Gentle Oud
- Italian Leather
- Wood Intense
- Khateer
- Basma
- Khayal
- Soudfa
- Rose Musk
- Rose Oud
- Rose Honey
- Rose Vanilla
- Daham

For the first twelve identities, `source_url` and `source_evidence_url` point to official individual product pages. Their 12 existing variant additions use the exact 90 ml / 100 ml and Eau de Parfum wording embedded in the official product URL paths; the rendered product page itself does not expose those attributes as structured fields. The next twenty-three identities have individual official page URLs and `source_verified_name` status, but no size or concentration has been inferred from their URL slugs. No new variants or formats are added for these twenty-three records.

## Scope exclusions

Room sprays and home-fragrance products are not perfume identities and must remain outside the perfume catalog. Gift bundles and discovery sets must not be converted into individual fragrance identities unless their component scents are explicitly identified. A collection or reseller listing can help discover candidates, but it should not be used to infer a product size or concentration.

## Validation

The regression tests verify all forty-seven upgraded official product URLs and identity status, the twelve explicit variant records and their evidence URLs, the thirty-five identity-only records' lack of inferred formats/variants, Lock & Key provenance, and unique variant IDs.

Across the three evidence passes, the catalog adds 12 explicit variants and upgrades thirty-five more existing identity records without adding variants. The current working snapshot remains 2,061 identities and 303 variants. It does not claim that the remaining 61 identities have been individually verified or that the Maison Asrar catalog is complete.
