# Paris Corner — Ministry of Oud official identity reconciliation
Date: 8 November 2026

## Scope

This change promotes eleven already-registered Ministry of Oud fragrance names into the canonical product catalog. Every name is present in the official Paris Corner Ministry of Oud collection, and each has an individual product detail page on the brand-owned Paris Corner storefront.

Official collection:
https://www.pariscornerperfumes.com/collections/ministry-of-oud

The collection currently lists 13 products. Two entries are not added as new fragrance identities:
- Ministry of Oud 50ml Signature Set is a multi-fragrance gift set, not a single canonical fragrance.
- Ministry of Oud - Thailand Oud in Cairo is already represented in the catalog.

## Eleven identities added

| Canonical identity | Official product page | Size | Concentration |
|---|---|---:|---|
| Ministry of Oud - Amber Oud | https://www.pariscornerperfumes.com/products/ministry-of-oud-amber-oud | 100 ml | Eau de Parfum |
| Ministry of Oud - Gladiators Oath | https://www.pariscornerperfumes.com/products/ministry-of-oud-gladiators-oath | 100 ml | Not stated |
| Ministry of Oud - Maestro's Symphony | https://www.pariscornerperfumes.com/products/ministry-of-oud-maestro-s-symphony | 100 ml | Not stated |
| Ministry of Oud - Nile Whispers | https://www.pariscornerperfumes.com/products/ministry-of-oud-nile-whispers | 100 ml | Not stated |
| Ministry of Oud - Oud Beyond the Wall | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-beyond-the-wall | 100 ml | Not stated |
| Ministry of Oud - Oud Indonesian | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-indonesian | 100 ml | Eau de Parfum |
| Ministry of Oud - Oud Royal | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-royal | 100 ml | Eau de Parfum |
| Ministry of Oud - Oud Satin | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-satin | 100 ml | Not stated |
| Ministry of Oud - Romance Reverie | https://www.pariscornerperfumes.com/products/ministry-of-oud-romance-reverie | 100 ml | Not stated |
| Ministry of Oud - Strictly Oud | https://www.pariscornerperfumes.com/products/ministry-of-oud-strictly-oud | 100 ml | Eau de Parfum |
| Ministry of Oud Greatest | https://www.pariscornerperfumes.com/products/ministry-of-oud-greatest | 100 ml | Eau de Parfum |

All eleven product pages explicitly identify the 100 ml size. Concentration is stored only for the five pages whose official copy explicitly describes Eau de Parfum/EDP. No concentration is inferred for the other six.

## Data changes

- Adds eleven canonical product records to `backend/product_catalog.json`.
- Adds one 100 ml variant per product.
- Uses individual official detail pages in both `source_url` and `source_evidence_url`.
- Adds `collection_name: Ministry of Oud`.
- Updates the existing Paris Corner family-registry records with `formats_ml: [100]`.
- No offers, prices, stock, shipping, or live availability are copied.

## Duplicate and category guardrails

The collection's 50 ml Signature Set is not imported as a perfume identity. The existing Thailand Oud in Cairo catalog identity is retained without duplication.

The family-registry discovery labels `Attratus` and `Harrier Absoulte` are not promoted as new canonical products: the catalog already contains `Attractus` and `Harrier Absolute` respectively. These spelling differences require alias/registry cleanup in a separate controlled change, not duplicate canonical identities.

## Snapshot after this change

- Canonical identities: 2,073
- Variants: 331
- Paris Corner identities: 258
- Paris Corner variants: 49

## Regression protection

`backend/tests/test_paris_corner_ministry_of_oud.py` checks the eleven official detail URLs, size, concentration evidence boundaries, one matching variant per identity, family-registry format alignment, unique variant IDs, and valid parent-product references.
