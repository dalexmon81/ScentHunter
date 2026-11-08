# Catalog snapshot reconciliation — 8 November 2026

## Scope

This audit records a direct structural read of `backend/product_catalog.json` at the requested-brand harvest snapshot (branch `catalog/requested-brand-harvest-2026-11-08`, head `50baaefcf8d2b1b5764cbaa40f691c8685ba5c56`). It does not claim worldwide or historical completeness for any brand.

## Reconciled snapshot

- Canonical fragrance identities: **2,061**
- Explicit variant rows: **291**
- Identities across the 20 requested brands: **2,058**
- Requested-brand identities marked `source_verified_name`: **186**
- Requested-brand identities marked `source_listed_name`: **1,872**
- Duplicate product IDs: **0**
- Duplicate variant IDs: **0**
- Orphan variants: **0**
- Variants with a missing/non-positive explicit size: **0**
- Product identities missing `source_url`: **0**

The PR #439 description contains an older **273 variants** figure in one section. The checked JSON at the current PR head contains **291**. The current JSON count is the source of truth for this audit; update the PR summary when appropriate.

## Requested-brand identity counts

| Brand | Identities | Individually detail-verified | Listing-level |
|---|---:|---:|---:|
| Velixir | 28 | 28 | 0 |
| Mykonos | 72 | 0 | 72 |
| Maison Asrar | 120 | 12 | 108 |
| Khadlaj | 116 | 3 | 113 |
| Bujairami | 142 | 20 | 122 |
| Paris Corner | 246 | 36 | 210 |
| Assaf | 140 | 7 | 133 |
| Al Wataniah | 86 | 2 | 84 |
| Armaf | 190 | 6 | 184 |
| French Avenue | 119 | 6 | 113 |
| Arabiyat Prestige | 118 | 22 | 96 |
| Gulf Orchid | 23 | 0 | 23 |
| Swiss Arabian | 32 | 4 | 28 |
| Games of Spades | 29 | 6 | 23 |
| Lattafa | 114 | 4 | 110 |
| Afnan | 87 | 1 | 86 |
| Aromatix | 12 | 0 | 12 |
| Maison Alhambra | 207 | 6 | 201 |
| Zimaya | 76 | 15 | 61 |
| Al Haramain | 101 | 8 | 93 |

## Variant provenance caveat

A direct field audit found 103 variant rows with their own `source_evidence_url` and 188 rows without that variant-level field. All 188 still point to a product identity with a product-level `source_url`; this does **not** prove that the parent page explicitly substantiates that exact size/concentration variant.

Do not automatically copy a product-level URL into `source_evidence_url`. That would make the schema look complete without adding evidence. The next data-model improvement should distinguish:
- identity evidence (why the fragrance identity exists);
- variant evidence (why a particular size/concentration exists);
- evidence type and scope (official detail page, official collection listing, authorized retailer, archive, etc.).

Until that work is implemented, missing variant-level evidence is an audit gap, not proof that a variant is false. Review each affected row against its original source before promoting or deleting it.

## Product-category boundary

This snapshot audit checks structural integrity and brand identity counts. It does not re-fetch all source pages or certify that every row is a perfume rather than a body mist, deodorant, room spray, diffuser, gift set, or other adjacent product. Category exclusions must continue to be enforced through source-level review and brand-specific regression tests.

## Regression guard

`backend/tests/test_catalog_snapshot_reconciliation.py` protects the current identity/variant minimums, requested-brand count baseline, uniqueness of IDs, valid parent references, positive sizes, and parent identity provenance. It deliberately does not invent missing variant evidence.
