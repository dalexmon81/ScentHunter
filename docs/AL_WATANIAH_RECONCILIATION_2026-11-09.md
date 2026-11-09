# Al Wataniah catalog reconciliation — 9 November 2026

## Result

- All 86 official collection identities remain in the catalog.
- 40 identities have an individually verified official detail page and one explicit 100 ml Eau de Parfum variant.
- The 34-variant branch and 9-variant branch shared three exact variant IDs (Lemon Souffle, Choco Truffle and Ameerati). Six further variants were unique to the nine-variant branch and have been added.
- No duplicate product IDs, duplicate variant IDs, orphan variants or product-format mismatches remain.
- Consolidated catalog totals: 2075 products and 384 variants.

## Safeguards

Existing canonical product IDs and collection membership were preserved. Product and variant evidence URLs point to the official Al Wataniah product pages. No retailer prices, stock, shipping, GTINs, MPNs or affiliate data were added.

No pull request was merged and no default-branch or production change was made.

## Validation

The detail-evidence regression test checks all 40 verified identities and their 100 ml EDP variants. The collection-harvest test retains all 86 official collection identities and checks the exact verified detail URL set.
