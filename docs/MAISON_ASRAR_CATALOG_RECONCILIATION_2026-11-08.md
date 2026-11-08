# Maison Asrar catalog reconciliation — 8 November 2026

## Source hierarchy and current counts

The brand-owned storefront is the primary source:
- All products: https://maisonasrar.com/collections/all
- Fragrances: https://maisonasrar.com/collections/perfume-sprays
- Collections: https://maisonasrar.com/collections

At the time of this audit, the official all-products collection displayed 130 products, while the dedicated Fragrances collection displayed 74 products. The storefront separately labels Room Spray and Home Fragrances in its navigation. Therefore the 130-item all-products count must not be interpreted as 130 perfumes.

An independent EU reseller's guide lists 116 scents and explicitly states that it is not the official Maison Asrar website. It is useful as a discovery and historical cross-check, but it is not treated as primary proof of brand ownership or a substitute for official product pages:
https://maisonasrarperfumes.eu/perfumes/

## Catalog snapshot

The working catalog snapshot contains:
- 120 Maison Asrar canonical identities.
- 12 identities already supported by official individual product pages before this change.
- 108 identities whose current evidence is collection-level or independent-reseller evidence.
- 3 additional Maison Asrar records — Plot Twist, Love Key and Unsolved Mystery — are listed on Gulf Orchid's own storefront. Their individual product pages explicitly label the brand as Maison Asrar and state 100 ml EDP. They are retained as Maison Asrar identities, and their existing variants now carry the corresponding page-level evidence URL. Gulf Orchid is the storefront/source for these Lock & Key releases; the records are not reassigned to Gulf Orchid as the fragrance brand.

The 120 identities should not be described as a verified, complete current range. Gulf Orchid's storefront independently confirms the three Lock & Key records above, but those are not counted among the twelve Maison Asrar-owned product-page upgrades in this change. The 74 official fragrance collection count is a current storefront snapshot; it does not establish that older or discontinued identities are invalid.

## Official detail-page upgrades in this change

Twelve existing identities were upgraded to individual official product pages:
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

For each identity, `source_url` and `source_evidence_url` now point to the official individual product page, and `identity_status` is `source_verified_name`. One explicit size/concentration variant was added for each of the twelve pages. No other product identities were added, removed or renamed.

## Scope exclusions

Room sprays and home-fragrance products are not perfume identities and must remain outside the perfume catalog. Gift bundles and discovery sets must not be converted into individual fragrance identities unless their component scents are explicitly identified. A collection or reseller listing can help discover candidates, but it should not be used to infer a product size or concentration.

## Validation

The added regression tests verify all twelve official product URLs, identity status, exact size, Eau de Parfum concentration, variant-level evidence, and unique variant IDs.

The catalog change adds 12 explicit variants. It does not claim that the remaining 108 identities have been individually verified or that the Maison Asrar catalog is complete.
