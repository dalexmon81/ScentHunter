# Zimaya detail-page verification — 2026-11-08

## Result

Eight existing Zimaya collection-listed identities were upgraded to official product-detail evidence. Each product page explicitly shows a 100 ml Eau de Parfum and an audience designation. Eight matching 100 ml EDP variant rows were added; the parent product records now declare `formats_ml: [100]` to satisfy the catalogue seed integrity contract.

| Canonical identity | Official product page |
|---|---|
| Cult | https://zimayaperfumes.com/products/cult |
| Exquisite | https://zimayaperfumes.com/products/exquisite |
| Sharaf Blend | https://zimayaperfumes.com/products/sharaf-blend-100ml |
| Grandeur | https://zimayaperfumes.com/products/grandeur-100ml |
| Crysta Oud | https://zimayaperfumes.com/products/crysta-oud-100ml |
| Farah | https://zimayaperfumes.com/products/farah |
| Amber Is Great | https://zimayaperfumes.com/products/amber-is-great-100ml |
| Bahjah | https://zimayaperfumes.com/products/bahja |

## Data quality

- Existing canonical product IDs were preserved.
- Existing collection-list identities were promoted to `source_verified_name`; no duplicates were created.
- Variant size is 100 ml and concentration is `Eau de Parfum`, exactly as shown on the official pages.
- No GTIN, MPN, price, stock, shipping cost, retailer URL or canonical image was invented.
- No retailer offers were added.

## Remaining Zimaya work

This is a detail-page verification batch, not a complete Zimaya import. The broader brand listing still needs pagination and detail-page checks. Two additional official product pages surfaced during this pass — Wujood (https://zimayaperfumes.com/products/wujood-100ml) and Luxor (https://zimayaperfumes.com/products/luxor-100ml) — but those identities are not currently present in the 70-name Zimaya seed. They are held for a separate, ID-safe identity addition rather than being silently assigned arbitrary IDs.

## Validation

`backend/tests/test_zimaya_detail_evidence.py` checks the eight source URLs, evidence status, 100 ml parent formats, matching 100 ml EDP variants, and absence of commercial offer fields.
