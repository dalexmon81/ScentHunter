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
