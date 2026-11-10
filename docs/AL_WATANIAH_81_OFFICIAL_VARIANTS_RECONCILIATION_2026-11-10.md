# Al Wataniah official detail reconciliation — 10 November 2026

> **Historical checkpoint:** the 81-variant figures below describe the earlier reconciliation pass. They are not the latest cumulative totals. See `AL_WATANIAH_CUMULATIVE_INTEGRATION_2026-11-10.md` for the current 86-identity / 84-variant snapshot.

## Verified individual product pages

The cumulative catalog retains 86 canonical Al Wataniah identities. This reconciliation keeps the official collection provenance from the 10 November storefront audit and restores individual product-page evidence separately.

- **81 products** have official detail pages explicitly stating **Type: Eau de Parfum** and **Volume: 100 ML**.
- Each has one canonical 100 ml Eau de Parfum variant. Its `source_evidence_url` points to the matching official product detail page.
- **2 products** — House Of Oud and Anwan — have individual official detail pages that establish identity but do not expose verified size and concentration in accessible page content. They remain identity-only, with no variant.
- **3 products** — Rawaee Noble, Rawaee Regina and Redaa — remain collection/listing-only. No size or concentration is inferred.

## Provenance rules

- `source_url` remains the official collection/listing source recorded by the storefront harvest.
- `source_product_url` identifies the individual official product detail page.
- `source_evidence_url` on each variant points to that same individual detail page.
- Product IDs, variant IDs, canonical names, collection names and aliases are preserved.
- The family registry receives `formats_ml: [100]` only for products with an explicitly evidenced 100 ml variant.
- No GTIN, price, currency, stock, availability or retailer offer data is inferred or added.

## Reconciliation totals

| Measure | Result |
|---|---:|
| Canonical Al Wataniah identities | 86 |
| Official detail-page identities | 83 |
| Explicit 100 ml Eau de Parfum variants | 81 |
| Identity-only detail pages | 2 |
| Collection/listing-only identities | 3 |
| New variants added to cumulative head | 0 |
| Existing variants enriched with detail provenance | 0 |

## Live official evidence spot-check

The following official product pages were reopened on 10 November 2026. Each visibly states Eau de Parfum and 100 ML:

- Kayaan Classic — https://www.alwataniah.com/products/kayaan-classic
- Milele — https://www.alwataniah.com/products/milele
- Lazuli — https://www.alwataniah.com/products/lazuli
- Rose Eclat — https://www.alwataniah.com/products/rose-eclat
- White Chocolate Ganache — https://www.alwataniah.com/products/white-chocolate-ganache
- Ain Emarat Extrait — https://www.alwataniah.com/products/ain-emarat-extrait

The regression suite checks the complete 81-product detail-page set against the canonical catalog and family registry.


## Subsequent official detail-page follow-up

After the 81-variant checkpoint above, three products previously recorded as collection/listing-only were reconciled against their individual official detail pages:

- Rawaee Noble — https://www.alwataniah.com/products/rawaee-noble — Type: Eau de Parfum; Volume: 100 ML.
- Rawaee Regina — https://www.alwataniah.com/products/rawaee-regina — Type: Eau de Parfum; Volume: 100 ML.
- Redaa — https://www.alwataniah.com/products/redaa — Type: Eau de Parfum; Volume: 100 ML.

One 100 ml Eau de Parfum variant was added for each, reusing the existing canonical product IDs. These pages are now recorded as `source_verified_name`, not listing-only identities.

**Latest cumulative result:** 86 official detail-page identities, 84 explicit 100 ml Eau de Parfum variants, two identity-only products (House Of Oud and Anwan), and no remaining listing-only Al Wataniah identities. No GTIN or commercial offer data was inferred.
