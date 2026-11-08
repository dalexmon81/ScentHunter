# Maison Asrar official 100 ml EDP variants — 8 November 2026

## Scope

This change adds four 100 ml Eau de Parfum variants for existing Maison Asrar canonical identities. The product pages are brand-owned pages; the brand's own blog provides explicit concentration and size evidence for each fragrance.

## Verified records

| Existing canonical identity | Size | Concentration | Product page | Brand evidence |
|---|---:|---|---|---|
| Jawhara Rouge | 100 ml | Eau de Parfum | https://maisonasrar.com/collections/jawhara-collection/products/jawhara-rouge-eau-de-perfum-100ml | https://maisonasrar.com/blogs/news/experience-the-luxury-perfumes-by-maison-asrar |
| Jawhara Black | 100 ml | Eau de Parfum | https://maisonasrar.com/products/jawhara-black-eau-de-perfum-100ml | https://maisonasrar.com/blogs/news/experience-the-luxury-perfumes-by-maison-asrar |
| Fresh Iris | 100 ml | Eau de Parfum | https://maisonasrar.com/products/fresh-iris-maison-asrar-eau-de-perfum-100-ml | https://maisonasrar.com/blogs/news/iris |
| Dear Jasmine | 100 ml | Eau de Parfum | https://maisonasrar.com/products/dear-jasmine-maison-asrar-eau-de-perfum-100-ml | https://maisonasrar.com/blogs/news/%D8%A7%D9%84%D9%8A%D8%A7%D8%B3%D9%85%D9%8A%D9%86 |

The official Jawhara article explicitly labels Jawhara Rouge and Jawhara Black as 100 ml Eau de Parfum. The official Fresh Iris article explicitly labels Fresh Iris as 100 ml Eau de Parfum. The official Arabic-language Maison Asrar article identifies Dear Jasmine as 100 ml Eau de Parfum in its product image/title, and the individual Dear Jasmine product page confirms the fragrance identity and EDP description.

## Catalog changes

- Four existing product records now point to individual brand-owned product pages in `source_url`.
- `source_evidence_url` points to the corresponding official brand article documenting size and concentration.
- All four existing identities are marked `source_verified_name`.
- Four explicit 100 ml EDP variants are added.
- Product-level `formats_ml` and the `maison_asrar_catalog` family registry are aligned.
- No new canonical identities, prices, offers, stock, shipping, or availability snapshots are added.

## Snapshot after change

- Total canonical identities: 2,062
- Total variants: 328
- Maison Asrar canonical identities: 120
- Maison Asrar variants: 7

## Regression protection

`backend/tests/test_maison_asrar_official_blog_variants.py` checks official product URLs, official blog evidence URLs, 100 ml EDP variant data, family-registry alignment, unique variant IDs, and valid parent product references.
