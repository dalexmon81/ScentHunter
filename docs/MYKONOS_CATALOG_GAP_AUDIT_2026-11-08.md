# Mykonos catalog gap audit — 8 November 2026

## Scope and safety

This is a read-only reconciliation report for the Mykonos records already present in `backend/product_catalog.json` on the head of PR #439 (`50baaefcf8d2b1b5764cbaa40f691c8685ba5c56`). It does not add, remove, rename, merge, or reclassify any product or variant. It does not change prices, availability, retailer offers, or production data.

## Snapshot measured directly from the catalog JSON

- Total canonical identities: **2061**
- Total explicit variants: **291**
- Mykonos canonical identities: **72**
- Mykonos explicit variants: **91**
- Mykonos identities with at least one explicit variant: **56**
- Mykonos identities without any explicit variant: **16**

The current PR #439 description reports 273 variants and 77 Zimaya identities. The actual JSON blob at the PR head measures 291 variants and 76 Zimaya identities. This is a documentation/count discrepancy to reconcile before treating the PR description as the canonical snapshot.

## Mykonos identities without an explicit variant

These 16 existing identities currently have no variant row:

- Only You
- Shades Perfume
- Chai Crema Latte
- Jynx
- Rouge
- Seven Roses
- Ivory
- Blossom
- Zora
- Down to Earth
- When in Paris
- Pandan Sticky Rice
- Pistachio Cream Cake
- Blaze
- Memoir of Meri
- Once Upon Don

They are retained as canonical identities. No size, concentration, or variant has been inferred for them.

## Source comparison

The brand-owned Indonesian storefront currently exposes its regional product assortment at:

- https://officialmykonos.com/collections/all
- https://officialmykonos.com/collections/all?page=2
- https://officialmykonos.com/collections/all?page=3
- https://officialmykonos.com/collections/all?page=4
- https://officialmykonos.com/products/mykonos-sansa-edp-travel-size-15ml

The official travel-size page lists 18 scent options at 15 ml. Those options have already been represented as variants of existing identities in the catalog; they are not 18 new canonical perfumes. The catalog currently has 91 Mykonos variants, including those 18 travel-size variants.

An authorized EU retailer's catalogue presents a broader regional/historical discovery index and reports 90 fragrances:

- https://mykonosperfumes.eu/pages/explore

That retailer catalogue is useful as a discovery lead, not as proof that every item is currently sold by the brand in Indonesia. Its count must not be added to the brand-owned store count. Names found only in the retailer catalogue should remain unpromoted until an individual product page or another acceptable source documents the product and its exact variant attributes.

## Variant evidence policy

For each of the 16 identities above, next research must find an individual product page or other authoritative product-level evidence that explicitly states:
- the exact perfume identity (not a bundle, gift set, body mist, or room product);
- the concentration, if recorded;
- each size, if recorded;
- whether a listed format is a refill, travel spray, tester, or standard retail bottle.

A collection page or authorized retailer listing may be recorded as discovery evidence, but must not be used to invent concentration or size. Where no adequate evidence is found, leave the identity without variants and record the gap.

## Structural integrity checks from the same JSON snapshot

- Duplicate product IDs: **0**
- Duplicate variant IDs: **0**
- Duplicate normalized brand/name pairs (simple trim + case-fold): **0**
- Orphan variants: **0**
- Variant sizes absent from the parent product's `formats_ml` (when checked against the same snapshot): **0**

These are structural checks only. They do not establish source authenticity or completeness.

## Requested-brand identity counts

- Velixir: 28
- Mykonos: 72
- Maison Asrar: 120
- Khadlaj: 116
- Bujairami: 142
- Paris Corner: 246
- Assaf: 140
- Al Wataniah: 86
- Armaf: 190
- French Avenue: 119
- Arabiyat Prestige: 118
- Gulf Orchid: 23
- Swiss Arabian: 32
- Games of Spades: 29
- Lattafa: 114
- Afnan: 87
- Aromatix: 12
- Maison Alhambra: 207
- Zimaya: 76
- Al Haramain: 101

The sum across the 20 requested brands is **2058**. This is a count of canonical identities, not variants or current commercial offers.

## Next action

Continue the Mykonos pass by checking the 16 no-variant identities against individual product pages and the authorized EU discovery catalogue. Add only identities or variants backed by suitable product-level evidence, in a separate catalog PR with regression tests. Keep this audit PR separate from PR #439 and do not merge either PR without explicit approval.
