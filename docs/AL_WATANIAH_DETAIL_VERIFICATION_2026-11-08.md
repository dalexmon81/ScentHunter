# Al Wataniah detail-page verification — 2026-11-08

## Result

Two existing Al Wataniah identities were verified against individual official product pages. Both pages explicitly state Eau de Parfum and 100 ml.

| Canonical identity | Official product page | Verified details |
|---|---|---|
| Lemon Souffle | https://www.alwataniah.com/products/lemon-souffle | Eau de Parfum, 100 ml |
| Choco Truffle | https://www.alwataniah.com/products/choco-truffle | Eau de Parfum, 100 ml |

## Catalogue changes

- Existing product IDs were preserved.
- Both records were upgraded to `source_verified_name` and their exact official product URLs were recorded.
- Added one 100 ml EDP variant for each identity.
- No gender, GTIN, MPN, price, stock, shipping value, retailer offer or image URL was inferred or invented.

## Scope warning

The official all-products page lists 108 items, but a collection total is not the same as a verified perfume identity count. This batch verifies two of the ten Al Wataniah names already present in the canonical seed; the other eight still need individual product-page evidence.

## Validation

`backend/tests/test_al_wataniah_detail_evidence.py` checks the two official URLs, evidence status, EDP concentration, 100 ml parent formats and corresponding variants.
