# Maison Asrar official product-name audit — 10 November 2026

## Scope

This follow-up reconciles seven existing Maison Asrar canonical identities against individual product pages on the brand's official storefront. Existing canonical product IDs are retained. No new products or variants are created.

## Verified names and primary sources

| Existing identity | Official product page | Result |
|---|---|---|
| Lumiere | https://maisonasrar.com/products/lumiere | Product name verified |
| Night in Paris | https://maisonasrar.com/products/night-in-paris-maison-asrar-eau-de-perfum-90ml | Product name verified |
| Patchouli with Love | https://maisonasrar.com/products/patchouli-with-love-maison-asrar-eau-de-perfum-100-ml | Product name and Eau de Parfum concentration verified in visible page copy |
| Pink Crush | https://maisonasrar.com/products/maison-asrar-pink-crush-eau-de-parfum-100-ml-for-women | Product name verified |
| Qamar | https://maisonasrar.com/products/qamar | Product name verified |
| Red Velvet | https://maisonasrar.com/products/maison-asrar-red-velvet-eau-de-parfum-100-ml-for-women | Product name verified |
| Rey | https://maisonasrar.com/collections/new-arrival/products/rey-eau-de-parfum-100ml-maison-asrar | Product name verified |

## Evidence limits

- The visible product-page content for these records does not expose a bottle size or GTIN.
- URL slugs containing strings such as `90ml`, `100-ml` or `eau-de-parfum` are not treated as sufficient proof of variant attributes.
- Patchouli with Love's visible official product description explicitly calls it an Eau de Parfum; this concentration is recorded on the canonical product only. No size or variant is inferred.
- The existing `maison_asrar_catalog` family-registry rows are retained without adding unverified `formats_ml`.
- Masterpiece was deliberately excluded: the discovered official-domain product URL identifies it as `gulf-orchid-masterpiece`, so brand attribution is unresolved and must not be guessed.

## Catalog changes

- Reuse the seven existing Maison Asrar product IDs.
- Upgrade only their identity evidence to `source_verified_name`.
- Set `source_url`, `source_product_url` and `source_evidence_url` to the individual official product pages.
- Record Eau de Parfum for Patchouli with Love because the visible official product copy states it explicitly.
- Do not create variants or add sizes, GTINs, prices, stock, availability, shipping or retailer-offer data.

## Regression coverage

`backend.tests.test_maison_asrar_official_name_audit_2026_11_10` verifies the seven existing canonical identities, individual official-page provenance, the one explicitly stated concentration, family-registry alignment, and global product/variant/GTIN integrity.
