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

# Al Wataniah official detail-page verification — 2026-11-09

## Result

Twelve existing Al Wataniah canonical identities were checked against their own brand-owned product pages. Every selected page explicitly states **Eau de Parfum** and **100 ml**. The canonical product IDs were preserved; one 100 ml EDP variant was added to each product.

| Canonical identity | Official product page |
|---|---|
| Kayaan Midnight | https://www.alwataniah.com/products/kayaan-midnight |
| Sabah Al Ward | https://www.alwataniah.com/products/sabah-al-ward |
| Sabah Al Ward Sugar | https://www.alwataniah.com/products/saba-al-ward-sugar |
| Special Oud | https://www.alwataniah.com/products/special-oud |
| Emiran | https://www.alwataniah.com/products/emiran |
| Cloud | https://www.alwataniah.com/products/cloud |
| Castilla | https://www.alwataniah.com/products/castilla |
| Fayroz | https://www.alwataniah.com/products/fayroz |
| Layali | https://www.alwataniah.com/products/layali |
| Praline Toffee | https://www.alwataniah.com/products/praline-toffee |
| Turquois | https://www.alwataniah.com/products/turquois |
| Royal Oak II | https://www.alwataniah.com/products/royal-oak-ii |

## Data handling

- No new canonical product identities were created.
- Existing product IDs and family-registry identities were preserved.
- Each product now records its individual product-page URL and `source_verified_name` status.
- Each product and its family-registry entry records the explicit 100 ml format.
- Each new variant uses the existing Al Wataniah variant-ID convention and stores its own official evidence URL.
- No prices, stock, retailer offers, GTINs, MPNs, shipping data or availability claims were imported.
- Product pages may show temporary sold-out or promotional information; that is not copied into the canonical catalog.

## Validation

Regression coverage in `backend/tests/test_al_wataniah_detail_evidence.py` checks the exact 12 URLs, identity uniqueness, product-page evidence, EDP concentration, 100 ml format and one matching variant per identity.

This is a focused detail-page reconciliation, not a claim that all 86 Al Wataniah catalog identities have individual product-page evidence.
