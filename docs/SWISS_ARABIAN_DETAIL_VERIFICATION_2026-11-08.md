# Swiss Arabian detail-page verification — 2026-11-08

## Result

Four existing Swiss Arabian identities were checked against official product-detail pages and upgraded to `source_verified_name`.

| Canonical identity | Official product page | Explicit detail |
|---|---|---|
| Shaghaf Oud | https://us.swissarabian.com/products/shaghaf-oud-3 | 75 ml, Eau de Parfum, Unisex |
| Casablanca | https://us.swissarabian.com/products/casablanca | 100 ml, Eau de Parfum, Unisex |
| Primal Code | https://us.swissarabian.com/products/primal-code | 100 ml, Eau de Parfum, for men |
| Valencia | https://de.swissarabian.com/en/collections/perfumes/products/valencia | Eau de Parfum, Unisex; size not stated in the retrieved page |

## Catalogue changes

- Existing canonical product IDs were preserved.
- Shaghaf Oud already had its explicit 75 ml EDP variant; its evidence URL was upgraded to the official product page.
- Added 100 ml EDP variants for Casablanca and Primal Code.
- Valencia was upgraded to product-detail evidence without inventing a size or variant.
- No GTIN, MPN, price, stock, shipping value, retailer offer or image URL was invented.

## Scope warning

The official Swiss Arabian all-products page reports 130 listings, but its catalogue includes incense and non-perfume product types. The 130 listing count must not be treated as 130 perfume identities. This batch verifies four existing perfume identities only; the remaining Swiss Arabian names still need detail-page verification and product-type filtering.

## Validation

`backend/tests/test_swiss_arabian_detail_evidence.py` checks all four official URLs, evidence status, concentration, and the two explicitly stated 100 ml variants plus the existing 75 ml Shaghaf Oud variant.
