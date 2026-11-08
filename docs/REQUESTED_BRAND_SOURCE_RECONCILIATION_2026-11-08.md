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


## Cross-PR integration audit — 8 November 2026

The following open draft PRs were compared by their actual head/base refs and by parsing the catalog snapshots. All four PRs below are open, draft, unmerged and reported mergeable at the time of this audit. The source-specific CI checks were completed successfully for #517 (two runs), #539 (one run) and #527 (two runs). The documentation-only #545 has no CI check run. No review submissions were present on #517, #527, #539 or #545.

### Velixir: #517 versus cumulative #527

- PR #517 (catalog/velixir-official-product-variants-2026-11-08, based on #515) contains 28 individual product-page URLs and 48 explicit EDP variants (35 ml / 100 ml), with the four Extrait identities correctly left without unsupported sizes.
- The Velixir product and variant records in #517 are identical on the compared catalog fields to the 28 identities / 48 variants already present in cumulative PR #527.
- However, #527 does not contain backend/tests/test_velixir_official_product_variants.py; the file is absent from that branch. Its workflow therefore does not run this dedicated Velixir regression test.
- Integration implication: do not duplicate the 48 catalog variants when integrating #517 into #527. Carry over the Velixir regression test, its workflow invocation, and its evidence document, then run validation on the integrated head.

### Mykonos: #539 versus cumulative #527

- PR #539 (catalog/mykonos-detail-evidence-2026-11-08, based on #439) promotes 15 existing identities to individual official detail-page evidence and updates 23 matching variant evidence URLs. It preserves 72 identities and 91 variants.
- Cumulative PR #527 contains 99 Mykonos identities and 102 variants. All 91 product/size/concentration keys present in #539 are also present in #527; #527 has 11 additional variant keys and 27 additional identities.
- Critical evidence regression: when the 15 detail-verified product rows from #539 are compared with the same canonical names in #527, only one of the 15 retains the same individual source_url. The other 14 are back at collection-level source_url values in #527. Thus, taking #527 as-is would lose most of the individual-page provenance established by #539.
- #527 does not contain backend/tests/test_mykonos_official_detail_evidence.py; the file is absent from that branch. The 11 extra variants in #527 are not covered by #539's test because they are outside #539's 72-identity snapshot.
- Integration implication: transplant the 15 product-level detail URLs and the 23 variant evidence URLs from #539 into the corresponding records in #527, without deleting the 27 extra identities or the 11 extra variant keys. Extend the Mykonos regression coverage to assert both the 15 official-page upgrades and the retained cumulative additions. Then run the full catalog validation on the integrated head.

### Bujairami and cumulative snapshot

- PR #527 is based on #502 and carries the cumulative snapshot of 2,743 identities / 717 variants, including 671 Bujairami identities / 8 variants, 99 Mykonos identities / 102 variants, and 28 Velixir identities / 48 variants.
- Its own cumulative integrity checks passed in the reported CI runs. This does not substitute for the missing Velixir and Mykonos source-specific regression tests noted above.

### Recommended integration sequence

1. Keep #517, #539 and #527 open and unmerged while the cumulative branch is reconciled.
2. Use #527 as the cumulative integration target for this batch because it already contains the larger Bujairami / Mykonos snapshot and the exact Velixir catalog rows.
3. Transplant the missing Velixir test + workflow hook + documentation from #517, and the Mykonos individual-page evidence + test + documentation from #539.
4. Preserve all 27 Mykonos identities and 11 Mykonos variant keys that exist only in #527; do not overwrite them with the smaller #539 snapshot.
5. Run the catalog-seed workflow on the resulting integration head and inspect the complete product/variant/registry integrity results before proposing any merge.

This is an integration audit and recommendation only. No catalog branch, existing PR, main, or production deployment was changed by this document update.
