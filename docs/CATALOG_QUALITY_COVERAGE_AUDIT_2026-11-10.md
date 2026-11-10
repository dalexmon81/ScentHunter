# Catalog quality and coverage audit — 10 November 2026

## Scope and method

Read-only structural audit of the cumulative catalog snapshot used by PR #654:
- `backend/product_catalog.json`
- `backend/family_registry.json`

This report measures existing data only. It does not infer a bottle size, concentration, GTIN, or missing variant from a product name, URL slug, retailer listing, or family-registry entry.

## Catalog snapshot

| Metric | Count |
|---|---:|
| Canonical products | 2,210 |
| Explicit variants | 970 |
| Products with at least one variant | 847 |
| Products marked `source_verified_name` | 1,060 |
| Products marked `source_listed_name` | 1,150 |
| Variants without concentration | 381 |
| Variants without a dedicated `source_evidence_url` | 178 |
| Variants without any source URL field | 146 |
| Orphan variants | 0 |
| Duplicate product IDs | 0 |
| Duplicate variant IDs | 0 |
| Duplicate GTINs | 0 |
| Duplicate product/size/concentration tuples | 0 |
| Variant records contaminated with commercial offer fields | 0 |

A product can be correctly verified as an identity while its size or concentration remains unknown. Therefore, the 255 `source_verified_name` products without a variant are a research queue, not a claim that 251 variants are missing.

Likewise, a missing concentration on a variant is not permission to infer one. Keep the value unset until first-party evidence explicitly supports it.

## Brand coverage and review queues

Counts below are calculated by joining variant `product_id` values to canonical product records.

| Brand | Products | Source-listed | Verified, no variant | Variants |
|---|---:|---:|---:|---:|
| Paris Corner | 254 | 5 | 61 | 188 |
| Maison Alhambra | 226 | 151 | 0 | 87 |
| Armaf | 218 | 127 | 48 | 90 |
| Al Haramain | 149 | 83 | 3 | 72 |
| Bujairami | 142 | 85 | 35 | 23 |
| Assaf | 140 | 103 | 1 | 39 |
| Lattafa | 135 | 40 | 8 | 87 |
| Maison Asrar | 120 | 95 | 22 | 3 |
| French Avenue | 119 | 93 | 1 | 37 |
| Arabiyat Prestige | 118 | 91 | 0 | 27 |
| Khadlaj | 116 | 16 | 0 | 112 |
| Afnan | 87 | 68 | 14 | 7 |
| Al Wataniah | 86 | 65 | 19 | 2 |
| Zimaya | 76 | 61 | 0 | 15 |
| Mykonos | 72 | 19 | 0 | 91 |
| Swiss Arabian | 41 | 28 | 1 | 12 |
| Gulf Orchid | 36 | 18 | 0 | 18 |
| Games of Spades | 32 | 1 | 28 | 8 |
| Velixir | 28 | 0 | 8 | 40 |
| Aromatix | 12 | 2 | 1 | 9 |
| Al Ambra | 2 | 2 | 0 | 0 |
| Giorgio Armani | 1 | 0 | 0 | 3 |

### Priority A — upgrade identity provenance

These brands have the largest source-listed queues and should be audited against current official brand product-detail pages before adding variants:

1. Maison Alhambra — 151 source-listed identities.
2. Armaf — 127.
3. Assaf — 103.
4. Maison Asrar — 95.
5. French Avenue — 93.
6. Arabiyat Prestige — 91.
7. Bujairami — 85.
8. Al Haramain — 83.

For each product, upgrade identity provenance only when the individual first-party page confirms the exact canonical identity. Do not infer variant attributes from collection cards or URL slugs.

### Priority B — investigate verified identities without variants

The largest queues are Paris Corner (61), Armaf (49), Bujairami (35), Games of Spades (28), Maison Asrar (22), Al Wataniah (19), and Afnan (14).

Inspect official product pages for explicit size/concentration options. Add only the variants supported by the page; otherwise retain a name-only canonical identity and document the unresolved fields.

### Priority C — repair variant evidence and attributes

- 178 variant records lack a dedicated `source_evidence_url`; 146 lack all three source URL fields.
- 381 variants have no concentration recorded.
- Highest concentration-unknown counts include Paris Corner (180), Lattafa (83), Assaf (39), Armaf (21), Bujairami (19), Mykonos (19), and French Avenue (12).

Review these records in batches. Reuse existing variant IDs when enriching evidence; do not create duplicates.

## Family registry note

The family registry contains 2,389 product entries across family groups, while the canonical catalog contains 2,210 product records. These are different structures and must not be treated as a one-to-one count. The registry's `formats_ml` field is discovery knowledge, not a substitute for canonical variant records or first-party evidence.

## Recommended next execution order

1. Upgrade official detail-page provenance for the Priority A source-listed identities.
2. Reconcile Priority B verified identities against official size/concentration selectors.
3. Backfill missing variant evidence URLs and concentrations where explicitly documented.
4. Keep ambiguous or contradictory brand pages unresolved and add regression tests for those deliberate omissions.
5. Re-run catalog integrity tests and compare counts against this snapshot after each batch.

## Safety boundary

This audit changes no product or variant data. No prices, stock, availability, shipping, retailer offers, or affiliate data are introduced. No changes are made to `main` or production.
