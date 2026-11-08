# Source refresh — requested fragrance brands (2026-11-08)

This is a source-discovery checkpoint for the requested catalogue expansion. It does **not** claim that these products have been imported into `backend/product_catalog.json`.

## New authoritative catalogue evidence

| Requested brand / line | Source evidence | Scope surfaced | Import treatment |
|---|---|---:|---|
| Paris Corner | Official all-products collection: https://www.pariscornerperfumes.com/collections/all | 252 products | Extract individual fragrance identities and distinguish Paris Corner-owned lines (Emir, Ministry of Oud, North Stag, Pendora, etc.) from standalone brands before import. |
| Lattafa | Lattafa USA all-fragrances collection: https://www.lattafa-usa.com/collections/all | Collection filters show 226 Lattafa Collection and 63 Lattafa Pride items; includes non-perfume types | Use as a discovery source only until the official regional domain/brand ownership and product-level records are reconciled. Exclude oils, deodorants, air fresheners and body sprays unless modeled separately. |
| Zimaya | Official all-products collection: https://zimayaperfumes.com/collections/all | 106 products | Strong import candidate. Separate EDP/extrait identities from concentrated oils and other formats. |
| Swiss Arabian | Official all-products collection: https://swissarabian.com/collections/all-products | 130 products | Strong import candidate. Exclude incense and non-fragrance formats from perfume identities; keep bottle sizes as variants. |
| Al Haramain | Official EU collection: https://shop.alharamainperfumes.com/eu/collection.html | 198 catalogue items across 5 pages | Strong import candidate. Product pages expose names, sizes and concentrations; collapse size-only duplicates into variants. Official e-catalogue: https://shop.alharamainperfumes.com/E-Catalog/e-catalog.pdf |

## Cross-checks and cautions

- Paris Corner's official UAE collection independently reports 268 perfumes: https://ae.pariscorner.com/collections/all. The difference from the 252-product global collection is a regional/catalogue-scope discrepancy; do not merge both counts as if they were unique identities.
- Fragrantica lists 205 Paris Corner fragrances, which is a useful cross-check but not a complete primary source: https://www.fragrantica.com/designers/Paris-Corner.html.
- Lattafa USA's storefront contains non-perfume products and should not be treated as an official exhaustive perfume identity list without confirming ownership/domain status.
- Zimaya's 106-product count includes a catalogue that must be filtered by product type.
- Swiss Arabian's 130-product collection includes incense and other non-perfume formats.
- Al Haramain's EU collection count is SKU/item count, not necessarily canonical fragrance identity count; multiple sizes/concentrations must be grouped carefully.

## Import order recommended

1. Zimaya (official list, 104 items; filter product types).
2. Swiss Arabian (official list, 130 items; filter product types).
3. Al Haramain (official EU collection, 198 SKUs; group variants).
4. Paris Corner (252 official collection items; normalize sub-lines and regional duplicates).
5. Lattafa (resolve official source/domain and product-type filtering before importing).

## Safety rules for this batch

- Do not invent GTIN/EAN, MPN, concentration, size, gender, image URL, stock or offer data.
- Do not create retailer offers from brand catalogue entries.
- Keep gift sets, samples, discovery kits, oils, incense, deodorants, air fresheners and body care out of the perfume identity list unless the schema explicitly supports those product types.
- Deduplicate by canonical brand + fragrance identity + concentration; represent bottle size as a variant.
- Preserve provenance per imported identity and leave unverified optional fields empty.
- No changes to production or the existing Liquid Brun validation work are included in this source-refresh checkpoint.

## Current status

Research sources have been refreshed and import priority is established. The central product catalogue has not been modified by this checkpoint. Actual import must follow extraction, normalization, deduplication and structural validation.
