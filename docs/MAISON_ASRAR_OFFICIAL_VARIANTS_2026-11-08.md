# Maison Asrar official 100 ml variants — 8 November 2026

## Scope

Adds nine 100 ml Eau de Parfum variants to existing Maison Asrar canonical identities. No canonical identities are added or removed. No retailer offers, prices, stock, or availability are imported.

## Manufacturer evidence

Maison Asrar's official product pages identify these variants:

| Product | Size | Concentration | Official product page |
|---|---:|---|---|
| Jawhara Rouge | 100 ml | Eau de Parfum | https://maisonasrar.com/collections/jawhara-collection/products/jawhara-rouge-eau-de-perfum-100ml |
| Jawhara Black | 100 ml | Eau de Parfum | https://maisonasrar.com/products/jawhara-black-eau-de-perfum-100ml |
| Fresh Iris | 100 ml | Eau de Parfum | https://maisonasrar.com/products/fresh-iris-maison-asrar-eau-de-perfum-100-ml |
| Basma | 100 ml | Eau de Parfum | https://maisonasrar.com/products/maison-asrar-basma-eau-de-parfum-100-ml-unisex |
| Vanilla Rouge | 100 ml | Eau de Parfum | https://maisonasrar.com/products/vanilla-rouge-maison-asrar-eau-de-perfum-100-ml |
| Petra | 100 ml | Eau de Parfum | https://maisonasrar.com/products/petra-maison-asrar-eau-de-perfum-100ml |
| Soudfa | 100 ml | Eau de Parfum | https://maisonasrar.com/products/maison-asrar-soudfa-eau-de-parfum-100-ml-for-women |
| Casablanca | 100 ml | Eau de Parfum | https://maisonasrar.com/products/casablanca-maison-asrar-eau-de-perfum-100ml |
| Dear Jasmine | 100 ml | Eau de Parfum | https://maisonasrar.com/products/dear-jasmine-maison-asrar-eau-de-perfum-100-ml |

The product-page URL slugs explicitly encode the size and Eau de Parfum designation. The official page title and product descriptions identify the corresponding fragrances. The current storefront may show some pages as sold out; this catalog change records product identity and variant attributes, not current availability.

## Catalog handling

- Existing canonical product IDs are preserved.
- Each parent product receives `formats_ml: [100]`.
- Each receives one distinct 100 ml Eau de Parfum variant.
- Both `source_url` and `source_evidence_url` point to the individual brand-owned product page.
- No price, stock, availability, or live offer is inferred from editorial or product-page content.

## Validation

`backend/tests/test_maison_asrar_official_variants.py` checks all nine identities, official page URLs, size, concentration, parent-format alignment, and global variant ID uniqueness.
