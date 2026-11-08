# Maison Asrar official 100 ml variants — 8 November 2026

## Scope

Adds three variants to existing canonical identities. No new product identities, retailer offers, prices, or stock values are added.

## Official manufacturer evidence

Maison Asrar's own article, “Experience the Luxury Perfumes by Maison Asrar” (28 May 2024), explicitly labels:
- Jawhara Rouge — Eau de Parfum 100 ml — https://maisonasrar.com/collections/jawhara-collection/products/jawhara-rouge-eau-de-perfum-100ml
- Jawhara Black — Eau de Parfum 100 ml — https://maisonasrar.com/products/jawhara-black-eau-de-perfum-100ml

Source: https://maisonasrar.com/blogs/news/experience-the-luxury-perfumes-by-maison-asrar

Maison Asrar's own article, “Secret of IRIS?” (28 May 2024), explicitly labels:
- Fresh Iris — Eau de Parfum 100 ml — https://maisonasrar.com/products/fresh-iris-maison-asrar-eau-de-perfum-100-ml

Source: https://maisonasrar.com/blogs/news/iris

## Catalog handling

- Existing canonical product IDs are preserved.
- Each product receives `formats_ml: [100]`.
- Each receives one distinct 100 ml Eau de Parfum variant.
- Each canonical product `source_url` points to its individual official product page; the brand article URL is retained in `source_evidence_url`.
- No price, stock, availability, or live offer is inferred from editorial content.

## Validation

`backend/tests/test_maison_asrar_official_variants.py` checks the three identities, official evidence URL, size, concentration, and global variant ID uniqueness.
