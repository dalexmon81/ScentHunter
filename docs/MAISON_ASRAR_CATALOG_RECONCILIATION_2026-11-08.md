# Maison Asrar catalogue reconciliation — 2026-11-08

## Scope and sources

- Official Maison Asrar store: https://maisonasrar.com/collections/all
- Official Maison Asrar perfume-sprays collection: https://maisonasrar.com/collections/perfume-sprays
- Official Black product page: https://maisonasrar.com/products/black-eau-de-perfum-100ml
- Independent EU range guide (not official): https://maisonasrarperfumes.eu/perfumes/
- Gulf Orchid product pages for Love Key, Plot Twist and Unsolved Mystery.

The official store's all-products collection mixes product categories; the separate perfume-sprays collection is the relevant perfume range. Room sprays, reed diffusers, bundles and other home-fragrance products are not perfume identities.

The independent EU range guide lists 116 perfume identities and records sizes where stated. It is not the brand's official website, so its evidence is explicitly identified as a secondary reference rather than first-party confirmation.

## Identity reconciliation

- All 116 names in the EU guide are present in ScentHunter's Maison Asrar catalog.
- Love Key, Plot Twist and Unsolved Mystery are retained as separate Maison Asrar identities. Gulf Orchid product pages identify the brand and explicitly state 100 ml EDP.
- Five additional Fragrantica-listed names are retained as name-only records: Amal, Asala, Red Carpet, Runway Girl and Smokey Eyes. Their status remains `source_listed_name`; no sizes or concentrations are inferred.
- Shaheen Black is held out because its brand attribution conflicts across sources; it is not added until the attribution is resolved.
- The seed's “Black Grapefruit” entry is removed as a duplicate display label: the official product page is titled “Black” and lists grapefruit among its notes. The canonical identity is Black.
- “Silver Elixer” remains the catalog spelling with “Silver Elixir” as an alias; “Rose” retains “Rosé” as a spelling alias.

**Final reconciled count: 124 Maison Asrar canonical identities.** This is a cross-source catalog union, not a claim that all products are currently available.

## Variant reconciliation and provenance

- 105 size variants are supported by the independent 116-name guide, which explicitly lists the sizes for those records.
- Three additional variants are supported by Gulf Orchid product detail pages: Love Key, Plot Twist and Unsolved Mystery, each explicitly labelled 100 ml EDP.
- Total: **108 variants**.
- The 105 guide-derived variants carry `source_evidence_url=https://maisonasrarperfumes.eu/perfumes/`.
- The three retailer-derived variants carry their individual Gulf Orchid product URLs in `source_evidence_url`.
- Concentration is set to Eau de Parfum only where the source explicitly states it. For 35 guide-derived size records, concentration remains unspecified.
- No price, stock status or retailer offer is imported.

## Exclusions

Room sprays, reed diffusers, bundles and non-perfume products remain outside the canonical perfume catalog. The five Fragrantica-only name records have no variants.

## Validation

- 124 Maison Asrar canonical identities.
- 108 variants with a non-empty, traceable `source_evidence_url`.
- 2,092 total canonical identities and 501 variant rows on this branch.
- Velixir remains at 28 identities and 112 variants.
- No duplicate product IDs, duplicate brand/name pairs, duplicate variant IDs or orphan variants.
- No guessed sizes or concentrations.
