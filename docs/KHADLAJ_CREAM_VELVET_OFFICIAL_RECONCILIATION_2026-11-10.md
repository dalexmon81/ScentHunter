# Khadlaj Cream Velvet official product reconciliation — 10 November 2026

## Result

Cream Velvet already existed as one canonical Khadlaj identity in the catalog, but it had only collection-level provenance and no explicit variant. This change upgrades that existing identity and adds one verified variant; it does not create a second product identity.

## First-party evidence

- Official individual product page: https://khadlaj-perfumes.com/products/cream-velvet-100-ml-extrait-de-parfum-for-women-best-perfumes
- The official product title states **Cream Velvet 100 ml Extrait de Parfum for Women**.
- The page exposes GTIN/SKU **6291107978819**.
- The official all-products collection independently classifies Cream Velvet as a **Perfume Spray** and lists **100 ML**. The collection is supporting context; the individual product page is the evidence for concentration and GTIN.

## Catalog mutation

- Preserve canonical product ID: `SH-KHADLAJ-142e4d1e`.
- Upgrade `identity_status` to `source_verified_name`.
- Set product-level `source_url`, `source_product_url`, and `source_evidence_url` to the individual official product page.
- Record `Extrait de Parfum` and `formats_ml: [100]`.
- Add exactly one 100 ml Extrait de Parfum variant with GTIN `6291107978819`.
- Align the existing `khadlaj_catalog` family-registry entry with the 100 ml size.

No prices, stock, availability, shipping, or retailer-offer data is copied into the canonical catalog.

## Regression coverage

`backend.tests.test_khadlaj_cream_velvet_official_variant` checks identity uniqueness, official-page provenance, the single variant, GTIN, concentration, size, and family-registry alignment.
