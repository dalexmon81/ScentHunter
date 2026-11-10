# Khadlaj official GTIN and gender audit — 10 November 2026

## Scope

This follow-up enriches four existing Khadlaj canonical products and variants already present in the cumulative catalog. No new product or variant IDs are created.

## Evidence-backed updates

| Product | Existing variant | Size | Concentration | Gender | GTIN |
|---|---|---:|---|---|---|
| Onyx Galaxy | SHV-SH-KHADLAJ-ONYX-GALAXY-100-EDP | 100 ml | Eau de Parfum | Men | 6298043072762 |
| Shiyaaka Snow | SHV-SH-KHADLAJ-bbb43d66-100-000 | 100 ml | Eau de Parfum | Men | 6291107979335 |
| Panache Angel Dust | SHV-SH-KHADLAJ-f26d9535-100-000 | 100 ml | Extrait de Parfum | Women | 6298043070829 |
| Sawaar Vanille Blanc | SHV-SH-KHADLAJ-24969f48-100-UNSPECIFIED | 100 ml | **Unspecified** | Women | 6298043070768 |

Individual first-party product pages:
- https://khadlaj-perfumes.com/products/khadlaj-onyx-galaxy-100-ml-eau-de-parfum-for-men
- https://khadlaj-perfumes.com/products/special-edition-shiyaaka-snow-100-ml-eau-de-parfum-for-men
- https://khadlaj-perfumes.com/products/panache-angel-dust-100-ml-extrait-de-parfum-spray-for-women-shop-online-dubai-uae
- https://khadlaj-perfumes.com/products/sawaar-vanille-blanc-100-ml-eau-de-parfum-spray-for-women

## Concentration conflict — Sawaar Vanille Blanc

The official Khadlaj storefront exposes the same SKU/GTIN, 6298043070768, on both an Eau de Parfum product page and an Extrait de Parfum product page for Sawaar Vanille Blanc. Because the official source conflicts, this audit records the consistent 100 ml size, Women gender and GTIN, but deliberately leaves concentration unset. The existing variant ID ending in `UNSPECIFIED` is preserved.

## Catalog changes

- Preserve all four existing canonical product IDs and variant IDs.
- Add confirmed GTIN and gender fields to the existing variant records.
- Standardize direct official product-page provenance on product and variant records.
- Align the existing Onyx Galaxy 100 ml family-registry format.
- Do not add price, stock, availability, shipping or retailer-offer data.

## Regression coverage

`backend.tests.test_khadlaj_official_new_launch_completeness_2026_11_10` verifies the four existing IDs, official provenance, GTINs, gender, family-registry alignment, global uniqueness and offer-data separation. It explicitly asserts that Sawaar Vanille Blanc remains without a concentration until the brand resolves the conflicting pages.
