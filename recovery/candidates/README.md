# Candidate reconciliation — recovery branch

Status: **isolated recovery candidate; not merged to main and not deployed.**

## Inputs
- Base commit when recovery began: `600e5f939f0657c3ee4cb0f4854828edd9b064e6`
- Current main now also contains the opt-in PostgreSQL guard from PR #774: `defe49283754281c81f540fbdc3ef5588097c692`
- Catalog seed source commit: `54d84edabd927f5c6a60616e176adc02a81b3af6`
- Catalog source PR: #425 (open draft; unchanged)

## Candidate runtime-path files on this isolated branch
- `backend/product_catalog.json`: source catalog seed from PR #425 (1,668 products, 141 variants).
- `backend/family_registry.json`: merged family registry. It preserves all source identities and the current-main `excluded_products` / `excluded_aliases` safety rules in four overlapping families.
- `backend/scenthunter_next_engine/verified_gtin_variant_map.json`: merged GTIN map. All four current-main records were exact matches in the five-record source registry.

Separate duplicate JSON copies were removed to avoid storing the same 1 MB catalog twice. Exact source blob SHAs remain in `recovery/snapshots/README.md`; original PR #425 and its branch remain unchanged.

## Structural checks
- products: 1,668
- variants: 141
- brands: 22
- duplicate product IDs: 0
- duplicate variant IDs: 0
- orphan variants: 0
- duplicate product-size variant pairs: 0
- family count: 31
- family internal duplicate names: 0
- missing product-family links: 0
- GTIN records: 5
- GTIN records with missing product/variant or wrong product link: 0

## Known limitations / review gates
- Variant evidence is uneven: 53 of 141 rows have a `source_evidence_url`; 88 do not. Concentration is present on 127 of 141 rows; 14 remain blank. Do not infer missing concentration or variant provenance from a parent product URL.
- The source seed labels 1,635 product names as `source_listed_name` and only 33 as `source_verified_name`. This is not equivalent to full product-detail-page verification.
- The family registry intentionally includes some products in both a dedicated line family and the general brand family (e.g. Khadlaj Shiyaaka, Lattafa Asad, French Avenue Liquid Brun). Cross-family repetition is retained; only within-family canonical duplicates are rejected.
- The catalog seed does not recover commercial offers, prices, stock or current retailer data.
- Do not promote this candidate until full CI, application import/search behavior and the PR #772 pilot are reviewed together.
