# Requested-brand source reconciliation — first batch (8 November 2026)

## Scope and safety

This is a research/audit checkpoint stacked on `catalog/requested-brand-harvest-2026-11-08`. It does not change `main`, production, PR #424, PR #437, or PR #439. No catalog identities, variants, prices, availability, or offers are added by this document.

The audit compares the current PR #439 seed with brand-owned catalogue pages. A collection/listing is treated as listing-level evidence only. A size or concentration is promoted to a variant only after the corresponding brand source makes that specific product/option explicit.

## Findings

### Velixir

Current seed on PR #439:
- 28 canonical identities.
- All 28 are labelled `source_verified_name`, but their `source_url` currently points to the generic `https://velixirparfums.com/collections/all`.
- **Zero explicit variant rows** are linked to these 28 identities.

Brand-site evidence:
- Brand storefront collection: https://velixirparfums.store/collections/all
- The collection page currently reports 30 items and exposes EDP / Extrait categories. Product cards display size selectors (100 ml, 35 ml, 3 ml, 2 ml) for many products.
- The 30-item count includes a visible `JTC Bundle`, which is a bundle and must not become a canonical perfume identity. The collection page also does not, by itself, prove that every size selector is available for every perfume.
- The official brand domain `https://velixirparfums.com/` has a separate Lineup page. The independent guide https://velixirperfumes.eu/perfumes/ explicitly says it is not the official site; it lists 28 perfume names, 24 EDP and four Extrait, and reports 35/100 ml for the EDP range and 100 ml for the four Extraits. This is a useful reconciliation aid, **not** the authority for promoting variants.

Decision:
- No new Velixir identities added.
- Do not add sizes from the collection-wide selector or the independent guide alone.
- Next action: inspect each official individual product page / variant selector and record product-specific size evidence. Correct the current generic product `source_url` values to individual product URLs where verified. Then add a regression test that checks source URL and explicit variant rows for the verified subset.

### Mykonos

Current seed on PR #439:
- 72 canonical identities.
- 91 explicit variants (including the 18 travel-size 15 ml options already reconciled).
- The current brand-owned all-products listing reports 54 products: https://officialmykonos.com/collections/all
- Official collections page: https://officialmykonos.com/collections

Decision:
- The 54-item live assortment is not proof that the other 18 canonical identities are invalid or discontinued. Preserve legacy/regionally listed identities unless first-party evidence establishes retirement.
- Continue reconciliation of each current listing product to individual product pages. The generic collection URL on some rows remains listing-level provenance, not individual-page verification.
- Do not infer availability from listing presence or sold-out status; catalog identity and commercial offer availability remain separate concepts.

### Bujairami

Current seed on PR #439:
- 142 canonical identities.
- Zero explicit variant rows across the inspected Bujairami identities.
- Most identities are listing-level and point to regional collection pages; a smaller subset has individual Australian product URLs.

Brand-site evidence:
- UAE brand storefront: https://bujairami.ae/
- UAE all-products collection: https://bujairami.ae/collections/all
- Australian brand storefront: https://bujairami.com.au/
- EU storefront: https://bujairami.eu/

The UAE homepage distinguishes inspired fragrances from the brand's own story/collection and presents new arrivals including Tea Splash, V-Luxe, ACE, Last Kingdom, Darkwood, Chic Wood, Delulu and Suns Out. These are discovery leads only until their individual product pages establish that each is a perfume and provide its actual specifications. Regional assortments must not be merged blindly.

Decision:
- No new Bujairami identities or variants added in this pass.
- Next action: reconcile the paginated regional catalogues against the 142 seed identities, classify original creations versus inspired fragrances without duplicating regional aliases, and inspect individual pages for product type, concentration and sizes.

## Quality rules for the next catalog PR

1. Individual product URL required before promoting a listing-level identity to detail-verified.
2. Variant size and concentration must be evidenced at variant/product-page level; do not transfer a concentration from a parent or another region without support.
3. Discovery sets, bundles, gift sets, deodorants, body sprays, room sprays, diffusers and body products are not standalone perfume identities.
4. Keep regional product differences explicit; do not collapse similarly named products unless brand/GTIN or source evidence supports identity.
5. Do not import prices, stock, shipping, or retailer offers from brand catalog pages.
6. Preserve existing product IDs and variants unless a proven duplicate or source correction requires a carefully reviewed change.

## Snapshot limitation

This is a first-batch source audit, not a claim that all 20 requested brands are complete. It records concrete gaps and safe next steps. Catalog changes will be made in a separate PR after individual product evidence is collected; regression tests will be proposed separately and must pass on their own head commit.
