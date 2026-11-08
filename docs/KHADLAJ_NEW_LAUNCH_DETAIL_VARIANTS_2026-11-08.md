# Khadlaj new-launch product-page evidence — 8 November 2026

## Scope

This change strengthens evidence for nine existing Khadlaj canonical identities. It adds seven explicit variants from individual pages on the brand-owned store and refreshes source evidence for two existing variants.

The official store labels itself the **KHADLAJ PERFUMES Official E-Store** and separates perfume sprays from perfume oils, home and ambiance, bakhoor, and gift sets. The broad New Launches collection is therefore not treated as a perfume-only list.

## Official collection context

- The Khadlaj New Launches collection reports 89 products at the time of inspection.
- Its dedicated Perfume Spray filter reports 74 products.
- The store's broader collections index contains many other product categories and must not be imported wholesale as wearable perfume identities.
- No new canonical identities are created in this PR. This is a detail-page evidence and variant-completion pass for records already in the catalog.

## Verified detail pages and variants

| Existing identity | Size | Concentration | Result |
|---|---:|---|---|
| Onyx Galaxy | 100 ml | Eau de Parfum | New explicit variant |
| Island Sun | 100 ml | Extrait de Parfum | Existing variant retained; detail-page evidence attached |
| Sueno | 100 ml | Extrait de Parfum | New explicit variant |
| Saraya | 60 ml | Extrait de Parfum | New explicit variant |
| Zayaan Silver | 100 ml | Eau de Parfum | New explicit variant |
| Qarar | 60 ml | Extrait de Parfum | New explicit variant |
| Ihthiraam | 60 ml | Extrait de Parfum | New explicit variant |
| Icon | 100 ml | Eau de Parfum | New explicit variant |
| Panache Angel Dust | 100 ml | Extrait de Parfum | Existing variant retained; detail-page evidence attached |

Individual official product pages:

- Onyx Galaxy: https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-onyx-galaxy-100-ml-eau-de-parfum-for-men
- Island Sun: https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-island-sun-100-ml-extrait-de-parfum
- Sueno: https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/sueno-100ml-extrait-de-parfum-for-women
- Saraya: https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-saraya-60-ml-extrait-de-parfum-spray-for-men-women
- Zayaan Silver: https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/zayaan-silver-fresh-aquatic-spicy-woody-eau-de-parfum-for-men
- Qarar: https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-qarar-unisex-bold-oriental-extrait-de-parfum
- Ihthiraam: https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/ihthraam-extrait-de-parfum-spray-oriental-unisex-fragrance
- Icon: https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-icon-100-ml-eau-de-parfum-spray-for-men
- Panache Angel Dust: https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/panache-angel-dust-100-ml-extrait-de-parfum-spray-for-women-shop-online-dubai-uae

## Catalog changes

- `source_url` and `source_evidence_url` point to the individual official product page for all nine records.
- `identity_status` is `source_verified_name` for all nine.
- Seven missing variant rows are added. Island Sun and Panache Angel Dust already had their explicit variants, so they are not duplicated.
- `backend/family_registry.json` is aligned with the verified size formats.
- No price, stock, offer, shipping, or availability snapshot is copied into the canonical catalog.

## Snapshot after change

- Total canonical identities: 2,061 (unchanged)
- Total variants: 315
- Khadlaj canonical identities: 116 (unchanged)
- Khadlaj variants: 36

## Regression protection

`backend/tests/test_khadlaj_official_new_launch_variants.py` checks official page URLs, verified size/concentration, one matching variant per identity, family-registry size coverage, unique variant IDs, and valid parent product references.
