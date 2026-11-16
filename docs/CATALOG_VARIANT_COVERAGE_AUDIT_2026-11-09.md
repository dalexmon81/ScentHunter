# Catalog variant coverage audit — 2026-11-09

## Scope and method

Read-only inspection of `backend/product_catalog.json` on PR #424 head
`a45a0a1cabf09dd926b5bd158a34dcbd4880a9e0`. Product variants were grouped by
`product_id`. No catalog records were changed and no retailer requests were made.

This is a seed-catalog coverage measurement, not a claim about live offers or
retailer stock. A product identity without a variant is searchable as an
identity, but it cannot yet represent a purchasable size/concentration tuple.

## Measured result

| Metric | Count |
|---|---:|
| Canonical fragrance identities | 1,389 |
| Explicit product variants | 512 |
| Fragrances with at least one variant | 327 |
| Fragrances without any variant | 1,062 |
| Fragrances with one variant | 216 |
| Fragrances with two variants | 50 |
| Fragrances with three variants | 50 |
| Fragrances with four variants | 9 |
| Fragrances with five variants | 2 |

Variant coverage is therefore **23.54%** of canonical identities (327 / 1,389).
The remaining **76.46%** have no explicit size variant. Do not manufacture
variants to improve this percentage.

## Largest brands in the no-variant queue

| Brand | Identities without variants |
|---|---:|
| Afnan | 60 |
| Hugo Boss | 43 |
| Rayhaan | 38 |
| Rasasi | 35 |
| Burberry | 26 |
| Valentino | 24 |
| Carolina Herrera | 22 |
| Cartier | 22 |
| Hermès | 22 |
| Jo Malone London | 22 |
| Tom Ford | 22 |
| Chloé | 22 |
| Lacoste | 22 |
| Issey Miyake | 21 |
| Serge Lutens | 20 |
| Davidoff | 20 |
| Tiziana Terenzi | 20 |
| Jovoy | 20 |
| Viktor & Rolf | 20 |
| Roja Parfums | 20 |
| Mancera | 20 |

## Data-quality rules for the next catalog pass

1. Verify each candidate against an individual official product page or an
   equally authoritative manufacturer feed. A collection-page listing alone
   does not prove size or concentration.
2. Add a variant only when its size is explicit. Record concentration only
   when the source states it; do not infer EDP/EDT from the product name,
   marketing copy, or common market convention.
3. Keep GTIN separate from variant existence. Missing GTIN is not by itself a
   reason to reject an otherwise verified size/concentration tuple.
4. Preserve source URLs and provenance at both product and variant level.
5. Deduplicate by canonical product + size + concentration before assigning
   variant IDs. Keep bottle size as variant metadata, not a second product.
6. Do not ingest retailer price, availability, or stock in this research pass.

## Priority sequence

Start with the largest no-variant brands only where official product-page
evidence can be collected efficiently. Afnan is the first candidate by queue
size, followed by Hugo Boss, Rayhaan, Rasasi and Burberry. For each brand,
publish a measured batch with its own source-backed regression tests; do not
bulk-convert the entire brand from collection listings.

## Verification context

- PR #424 head `a45a0a1cabf09dd926b5bd158a34dcbd4880a9e0` passed the
  Catalog-first PostgreSQL vertical-slice workflow
  [42574270479](https://github.com/dalexmon81/ScentHunter/actions/runs/42574270479)
  and API contract workflow
  [42574270516](https://github.com/dalexmon81/ScentHunter/actions/runs/42574270516).
- The CI seed step independently reported 512 variants and 1,062 products
  without variants. It also reported zero stores seeded and zero source-backed
  variants added. This is fixture/seed CI, not live retailer acceptance.
- PR #592 cross-PR catalog collision audit passed on head
  `3340eb7a86c69119146cac2b4b655f9ec2d95f62`: 25 candidate PRs scanned,
  115 identical additions reported informationally, and zero conflicting
  product/variant identities detected. The seed regression suite ran 136 tests.
- No PR was merged, no live retailer was activated, and no production or
  traffic rollout was performed.
