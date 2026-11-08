# Catalog live-source recheck — 2026-11-08

## Purpose

This is a source recheck for the requested fragrance-house expansion on
`catalog/complete-brand-expansion-2026-11`. It does not create canonical
identities, variants, retailer offers, prices, stock, shipping values or GTINs.
A listing count is not treated as a count of unique perfume identities.

## Sources checked

### Paris Corner

- Official global all-products collection:
  https://www.pariscornerperfumes.com/collections/all
  The live collection search result reports 252 listings and explicitly groups
  Paris Corner with Emir, Ministry of Oud, North Stag, Pendora and Magic Oud
  Series. These are distinct collection/brand labels; the count includes
  products beyond the exact Paris Corner parent label and cannot be imported
  wholesale as perfume identities.
- Official European shop:
  https://it.pariscornereurope.com/collections/all
  The European storefront currently reports 148 products. This is a
  country/market-specific assortment and must not be merged blindly with the
  global site.
- Decision: retain existing parent/line attribution. Do not infer missing
  identities from either headline count. Continue a paginated, name-level
  comparison, classify sets/body products separately, and retain individual
  product-detail URLs for accepted identities.

### Maison Asrar

- Official global brand site:
  https://maisonasrar.com/
  Current storefront presents individual perfume products including Vanilla
  Voyage, Vanilla Aura, Belgravia, Vanilla Seduction, Fakhama, Milky Way,
  Coffee Blend, Soirée, Veyra, Dubai Miami, Legacy, Faris Al Arab, III
  Thriller, Vanguard, Regent, Majesty, Muharib, DXB and Vision.
- Independent fragrance index:
  https://maisonasrarperfumes.eu/fr/perfumes/
  The index reports 116 scents and provides a product-name list. It is useful
  as a cross-check, not as the manufacturer's authoritative inventory.
- Decision: do not assert the 121 Maison Asrar canonical identities are
  exhaustive or all currently marketed. A strict name-by-name diff between the
  official site and independent index is still required; preserve Royal
  Collection membership only where the official collection page supports it.
  Exclude room/home fragrance and bundles from standalone perfume identities.

### Khadlaj

- Official brand storefront:
  https://khadlaj-perfumes.sa/
  The navigation and collections separate perfume sprays, perfume oils,
  home/ambience products, gift sets and La Fede. The visible range includes
  Shiyaaka, Island Sun, Muse, Onyx Gold, Karus Gold Absolu, Nuha Bon Bon,
  Nafais Magrib, Titan and Zayaan Gold.
- Decision: do not use the site's broad all-products count as perfume count.
  Continue from the dedicated perfume-spray and La Fede collections, then
  verify individual product details. Oils, bakhoor, home fragrance and sets
  need separate product types or exclusion.

## CI and branch safety

The GitHub integration did not return workflow runs or commit status checks
for the current branch head inspected during this recheck. This document is
not a CI result. Run the repository's normal Actions workflow against the
current head before calling the catalog PR validated.

No production branch, production database, store credentials, deployment,
feature flag, retailer activation or traffic routing was changed. No offer,
price, availability, shipping or GTIN data was fabricated.

## Next acceptance gates

1. Run the full test suite and seed/import dry-run against the exact PR head.
2. Produce per-brand source-to-catalog name diffs, including missing, extra,
   alias and duplicate buckets.
3. Resolve the Mykonos 72-versus-53 discrepancy with evidence; do not bulk-add
   or bulk-delete names based on a listing total.
4. Finish the remaining paginated/product-level work for Paris Corner,
   Armaf, Khadlaj, Maison Asrar and the other brands marked partial in the
   coverage audit.
5. Keep this catalog-only PR separate from the Liquid Brun live-offer test.
