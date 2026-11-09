# Requested-brand catalog audit follow-up — 8 November 2026

## Scope and safety

This is an audit note only. It does not change canonical product rows, variants, family assignments, prices, stock, availability, or offers. It is based on the catalog blob at commit `50baaefcf8d2b1b5764cbaa40f691c8685ba5c56` (read via its Git blob SHA) and publicly indexed discovery sources. A discovery source is not treated as sufficient evidence for catalog insertion.

## Catalog snapshot at audited commit

- Canonical identities: **2,061**
- Explicit variants: **291**
- Requested brands: **20/20 represented**
- Duplicate product IDs: **0**
- Duplicate variant IDs: **0**
- Requested-brand product rows missing `source_url`: **0**

| Brand | Identities | Explicit variants | Detail-page evidence rows |
|---|---:|---:|---:|
| Velixir | 28 | 0 | 28 |
| Mykonos | 72 | 91 | 0 |
| Maison Asrar | 120 | 3 | 12 |
| Khadlaj | 116 | 29 | 3 |
| Bujairami | 142 | 2 | 20 |
| Paris Corner | 246 | 33 | 36 |
| Assaf | 140 | 8 | 7 |
| Al Wataniah | 86 | 2 | 2 |
| Armaf | 190 | 21 | 6 |
| French Avenue | 119 | 20 | 6 |
| Arabiyat Prestige | 118 | 22 | 22 |
| Gulf Orchid | 23 | 0 | 0 |
| Swiss Arabian | 32 | 3 | 4 |
| Games of Spades | 29 | 0 | 6 |
| Lattafa | 114 | 4 | 4 |
| Afnan | 87 | 4 | 1 |
| Aromatix | 12 | 0 | 0 |
| Maison Alhambra | 207 | 22 | 6 |
| Zimaya | 76 | 15 | 15 |
| Al Haramain | 101 | 9 | 8 |

“Detail-page evidence rows” counts `identity_status == source_verified_name`; it is a catalog label, not an independent revalidation of every URL in this audit. The large difference between identities and variants is intentional where size/concentration is not explicitly supported. Do not infer that a zero variant count means a brand has no retail variants.

## Discovery leads checked against the seed

A recent secondary release feed lists several products that are useful leads for official-source review. The seed already contains the following names:
- Armaf — Odyssey Mandarin Sky Elixir
- Bujairami — Top Tier
- Bujairami — Last Kingdom
- Paris Corner — Nawal
- Khadlaj — Panache Eleganza
- Khadlaj — Sueno
- Arabiyat Prestige — Mutheer
- Arabiyat Prestige — Mutheer Elixir

The same feed lists these names, which were **not found as exact canonical-name matches** in the audited seed:
- Bujairami — Full Effect
- Paris Corner — Nilgiris Silent Peaks
- Paris Corner — Nilgiris Mistvale
- Lattafa — Falsafat
- Lattafa — Asad Polar

These five are **not imported by this audit**. Search discovery and retailer listings are not enough to establish the required first-party identity and variant evidence. In particular, no usable official individual product-detail URL with confirmed specifications was obtained for these candidates during this pass. They remain an explicit verification queue, not catalog facts.

Discovery reference (secondary, not accepted as insertion evidence):
- https://scentradar.eu/news/

Official source checked for Armaf's existing Odyssey Mandarin Sky Elixir:
- https://armaf.com/

Official Armaf new-launch collection, useful for discovery but mixed-category:
- https://armaf.com/collections/new-launches

The Armaf collection itself shows why category filtering is mandatory: it includes body mists, body sprays, gift sets, all-over sprays and perfume products. Only fragrance identities supported by product-specific evidence belong in the canonical perfume catalog.

## Required next verification pass

For each outstanding candidate:
1. Find a first-party brand-owned collection or product page.
2. Open the individual product page and capture the exact canonical name and URL.
3. Record concentration and size only if explicitly stated for that product/variant.
4. Check whether the item is a perfume spray rather than oil, deodorant, body mist, room spray, diffuser, gift set or bundle.
5. Match by brand + normalized name and check existing product/variant IDs before proposing an insertion.
6. Add a regression test for every accepted identity/variant and preserve its provenance URL.
7. Do not add prices, stock, availability or retailer offers from discovery pages.

## Integrity notes

- This note does not claim that all 20 brand catalogs are complete.
- It does not mark absent or older identities as discontinued.
- It does not promote secondary-source-only leads.
- It does not modify `main`, PR #424, PR #437 or PR #439.

## Snapshot discrepancy to reconcile

The PR #439 description currently reports **273 explicit variants**, while parsing the `product_catalog.json` blob at its recorded head commit `50baaefcf8d2b1b5764cbaa40f691c8685ba5c56` yields **291 variant rows**. The audit count above is the direct JSON row count. This discrepancy should be reconciled in a dedicated follow-up before anyone relies on the PR description's variant total. The requested-brand coverage test currently checks per-brand minimum identity counts and selected variant cases; it does not assert the catalog-wide variant total.
