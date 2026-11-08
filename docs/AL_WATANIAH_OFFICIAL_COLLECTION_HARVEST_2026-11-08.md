# Al Wataniah official collection harvest — 2026-11-08

## Result

- 86 distinct fragrance identities reconciled from the brand's four official perfume collections.
- 10 identities were already in the catalog.
- 76 new canonical identities were added.
- The Al Wataniah catalog now contains 86 identities.
- The family registry contains all 86 collection identities; it also retains 12 homepage items marked "Launching Soon" as discovery-only family candidates, not published product identities.

## Official collection sources

| Collection | Listing count | Source |
|---|---:|---|
| Classic | 47 | https://www.alwataniah.com/collections/classic |
| Eternal | 22 | https://www.alwataniah.com/collections/eternal |
| Niche | 9 | https://www.alwataniah.com/collections/niche |
| Munchies | 8 | https://www.alwataniah.com/collections/munchies |
| **Total** | **86** | |

The four collections are perfume collections. The general all-products pages also contain perfumed body mists and air fresheners, so those categories were not imported as perfume identities.

## Data quality

- New names are marked `source_listed_name` and point to the exact official collection page.
- Lemon Souffle and Choco Truffle retain their earlier individual official product-page evidence and explicit 100 ml Eau de Parfum variants.
- No size or concentration was inferred for collection-only names.
- No prices, stock, shipping, GTINs, retailer offers or affiliate data were added.
- Names were deduplicated across collection pages; each canonical identity appears once.
- Homepage entries explicitly marked "Launching Soon" were excluded from the product catalog.

## Validation

`backend.tests.test_al_wataniah_official_collection_harvest` verifies the 86 expected identities, collection provenance, family-registry coverage and the rule that only the two individually verified products retain explicit variants.
