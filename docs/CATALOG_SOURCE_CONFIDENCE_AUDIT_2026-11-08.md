# Canonical catalog source-confidence audit — 2026-11-08

## Snapshot
Branch: `catalog/complete-brand-expansion-2026-11`

- Canonical product identities: **1,698**
- Explicit variants: **141**
- Brand labels: **22**
- Every identity has a `source_url` or `source_evidence_url`.
- No identity is missing its brand or canonical name.
- Evidence status:
  - `source_verified_name`: **42**
  - `source_listed_name`: **1,656**

## Interpretation
The catalog is a usable identity seed, but it is not a fully product-page-verified master catalog. Most entries are currently backed by a collection/index listing. A collection listing can support the existence of a fragrance name, but does not automatically establish its exact product page, SKU, GTIN, size, concentration, current availability or retailer offer.

The `family_registry.json` is explicitly loaded by `backend/main.py` as a supplement for registered legacy families; `product_catalog.json` remains the primary identity source. Therefore, the family registry is not expected to be a complete one-to-one mirror of all catalog identities. Differences between its family-name lists and the canonical catalog are not automatically catalog omissions, but should be reviewed before any change to matcher behavior.

## Next verification priorities
1. Armaf — 190 source-listed identities.
2. Maison Alhambra — 203 source-listed identities.
3. Paris Corner — 243 source-listed identities.
4. Bujairami — 121 source-listed identities.
5. French Avenue — 117 source-listed identities.
6. Arabiyat Prestige — 116 source-listed identities.

For each brand, reconcile paginated official fragrance-only collections and product-detail pages. Store product-level URLs only when verified. Keep sets, body products, home fragrance, oils/attars and collection aliases out of standalone perfume identities unless the product model explicitly supports them.

## Data safety
- Do not infer GTINs, stock, prices, shipping or availability.
- Do not create a variant from a size shown only on a general brand page.
- Do not silently merge names based only on text similarity.
- Keep uncertain candidates in a review overlay rather than promoting them into the canonical seed.
- No production database, retailer connector activation or deployment was changed in this audit.


## Official catalogue spot-check — 2026-11-08

### Armaf
- Official all-fragrances collection: https://armaf.com/collections/all-perfumes
- The current page reports 464 listings, but its own filters mix 248 Eau de Parfum items with body mist, body spray, deodorant, lotion, roll-on, shampoo, shower gel, soap and other formats.
- Do not import 464 as perfume identities. Use fragrance-only filters and product-detail pages; keep sets and body-care formats separate.

### Paris Corner
- Official all-products collection: https://www.pariscornerperfumes.com/collections/all
- The page currently reports 252 products and explicitly includes the separate labels/collections Ministry of Oud, Paris Corner, North Stag, Pendora, Emir and Magic Oud Series.
- This is a mixed parent-company feed, not 252 Paris Corner-branded standalone perfumes. Brand/line attribution and pagination must be reconciled before import.

### Bujairami
- Official all-products collection: https://bujairami.com.au/collections/all
- The current page reports 1,262 listings. Its collection navigation and product titles show a broad assortment of inspired-by fragrances, Bujairami original creations, niche line items and body sprays.
- The 1,262 listing count must not be treated as 1,262 original Bujairami perfume identities. Keep inspired-by products clearly attributed and distinguish them from original creations; exclude body sprays from the perfume identity set unless modeled as a separate format.
- Independent fragrance database cross-check: https://www.fragrantica.com/designers/Bujairami.html (325 entries). This is a secondary reference, not the primary source of truth.

### Afnan and Lattafa
- Afnan Europe official all-products listing: https://www.it.afnan.com/en/collections/all-products . Its navigation distinguishes fragrance categories, collections and gift sets, and the regional store can vary by shipping country.
- Lattafa official perfume category: https://lattafa.com/product-category/perfumes/ . The category is paginated and exposes product names; the broader brand/shop pages also contain discovery sets, personal care, home products and gift sets.

## Decision from this spot-check
No additional identities were imported from these collection totals alone. The evidence confirms that raw collection counts are not equivalent to canonical perfume counts. The next safe import pass must be product-name-level, page-by-page, with product URLs and format classification. This audit is documentation only; no catalog rows, variants, prices, stock, offers or production data were changed by this spot-check.
