# Candidate reconciliation — recovery branch

Status: **review candidate only; not active runtime data; not merged to main.**

## Inputs
- Current main commit: `600e5f939f0657c3ee4cb0f4854828edd9b064e6`
- Catalog seed source commit: `54d84edabd927f5c6a60616e176adc02a81b3af6`
- Catalog source PR: #425 (open draft)

## Candidate files
- `product_catalog.pr425.json`: preserved catalog seed from PR #425.
- `family_registry.merged.json`: PR #425 family registry plus current-main family entries, merged by family_id and canonical_name; aliases and exclusions are unioned.
- `verified_gtin_variant_map.merged.json`: union of PR #425 and current-main verified GTIN records. Shared GTIN records were byte-identical.

## Structural checks
- products: 1668
- variants: 141
- brands: 22
- duplicateProductIds: 0
- duplicateVariantIds: 0
- orphanVariants: 0
- duplicateVariantTuples: 0
- familyCount: 31
- familyInternalDuplicateNames: []
- missingProductFamilies: 0
- gtinRecords: 5
- gtinMissingProduct: 0
- gtinMissingVariant: 0
- gtinWrongProductVariant: 0
- mainOnlyFamilies: []

## Known limitations / review gates
- The 141 variant rows in the seed have no variant-level `source_url`; do not infer concentration or provenance beyond the product-level evidence.
- The source seed labels 1,635 product names as `source_listed_name` and only 33 as `source_verified_name`. This is not equivalent to full product-detail-page verification.
- The family registry intentionally includes some products in both a dedicated line family and the general brand family (e.g. Khadlaj Shiyaaka, Lattafa Asad, French Avenue Liquid Brun). Cross-family repetition is retained; only within-family canonical duplicates are rejected.
- The current-main catalog JSON is empty, so this candidate preserves the PR #425 catalog and does not claim to recover commercial offers or current retailer data.
- Do not promote this candidate until full test suite, application import/search tests, and the PR #772 pilot integration are validated together.
