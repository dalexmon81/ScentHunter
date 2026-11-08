# Paris Corner catalog and family-registry reconciliation — 2026-11-08

## Scope and source interpretation

Paris Corner's official global store separates the umbrella catalog into several
series/collections. Current official listing snapshots report:
- All products: 252 listings
- Paris Corner parent collection: 104 listings
- Emir: 54 listings
- Pendora Scents: 36 listings
- North Stag: 10 listings
- Ministry of Oud: 13 listings
- Ministry of Gourmand: 8 listings
- Magic Oud Series: 5 listings

These collection totals overlap and represent different storefront scopes.
They must not be added together or interpreted as unique canonical perfume
counts. The parent brand and series are therefore kept as a single canonical
brand/family for this seed pass; sub-series remain visible in source URLs and
product names where already present. No new variants were inferred from
collection counts.

Official references:
- https://www.pariscornerperfumes.com/collections/all
- https://www.pariscornerperfumes.com/collections/paris-corner
- https://www.pariscornerperfumes.com/collections/emir-1
- https://www.pariscornerperfumes.com/collections/pendora-scents-1
- https://www.pariscornerperfumes.com/collections/north-stag-1
- https://www.pariscornerperfumes.com/collections/ministry-of-oud
- https://www.pariscornerperfumes.com/collections/ministry-of-gourmand
- https://www.pariscornerperfumes.com/collections/magic-oud-series

## Branch corrections

The branch contained 253 Paris Corner-branded canonical rows and only 18
matching family-registry entries. Exact-name comparison found a registry
coverage gap. The reconciliation:
1. Added the remaining existing catalog identities to
   `paris_corner_catalog` in `family_registry.json`, without creating new
   canonical product rows.
2. Corrected the malformed family ID `paris-corner_catalog` to
   `paris_corner_catalog` for all affected products.
3. Removed the non-fragrance collection label `Ministry of Gourmand`
   (product ID `SH-PARIS-CORNER-MINISTRY-OF-GOURMAND-027`) from the canonical
   product seed. Actual Ministry of Gourmand perfumes remain as products.
4. Preserved all other canonical product IDs and existing variant rows.

## Verification

Exact branch-side comparison after the change:
- Paris Corner canonical products: 252
- Paris Corner family-registry entries: 252
- Catalog-only names: 0
- Registry-only names: 0
- Incorrect family IDs: 0
- Duplicate canonical names / product IDs within Paris Corner: 0
- Paris Corner variants retained: 31

Added five regression tests at
`backend/tests/test_paris_corner_catalog_parity.py` covering registry
parity, family IDs, official source URLs, exclusion of the collection label,
and uniqueness.

The whole branch now contains 1,940 canonical products and 270 variants.
These are branch-seed counts, not a claim that every historical or regional
Paris Corner release is covered. CI must still execute against the final PR
head; no offers, prices, stock, GTINs or shipping data were added.
