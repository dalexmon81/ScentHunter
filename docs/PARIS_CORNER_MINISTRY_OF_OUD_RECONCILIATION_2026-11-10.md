# Paris Corner Ministry of Oud reconciliation — 10 November 2026

## Official collection and product-level evidence

The official Ministry of Oud collection currently lists 13 entries, including five individual fragrance products that were present in the Paris Corner family registry but had not yet been promoted into the canonical catalog.

Verified individual official product pages:

| Canonical product | Official page | Size | Concentration |
|---|---|---:|---|
| Ministry of Oud - Amber Oud | https://www.pariscornerperfumes.com/products/ministry-of-oud-amber-oud | 100 ml | Eau de Parfum |
| Ministry of Oud - Oud Indonesian | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-indonesian | 100 ml | Eau de Parfum |
| Ministry of Oud - Oud Royal | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-royal | 100 ml | Eau de Parfum |
| Ministry of Oud - Oud Satin | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-satin | 100 ml | Not stated on retrieved page |
| Ministry of Oud - Strictly Oud | https://www.pariscornerperfumes.com/products/ministry-of-oud-strictly-oud | 100 ml | Eau de Parfum |

The product pages state the bottle size. Four pages explicitly describe the fragrance as EDP/Eau de Parfum. Oud Satin's retrieved page does not state concentration, so that field remains unset.

## Catalog changes

- Promoted the five existing family-registry discovery identities into canonical products.
- Added one 100 ml variant per product.
- Reused the existing family-registry entries and synchronized their `formats_ml` to `[100]`.
- Added individual official product-page provenance to both canonical products and variants.
- Added no GTIN, SKU, price, stock, availability, retailer offer or shipping data.

## Registry spelling reconciliation

Two discovery-only labels were not separate canonical fragrances:
- `Attratus` is a spelling variant of the existing canonical `Attractus`.
- `Harrier Absoulte` is the official storefront's misspelled display spelling for the existing canonical `Harrier Absolute`.

Both spellings are retained as aliases on their canonical family-registry rows; the duplicate registry-only rows are removed. No additional product IDs are created for these spellings.

## Result

- Paris Corner canonical products: 259.
- Paris Corner family-registry entries: 259.
- Catalog-only names: 0.
- Registry-only names: 0.
- New canonical products: 5.
- New explicit variants: 5.
- Product IDs and variant IDs remain unique.

## Validation

Added `backend.tests.test_paris_corner_ministry_of_oud_official_detail_audit_2026_11_10` and tightened `test_paris_corner_catalog_parity` to require exact catalog/registry name parity, while retaining known misspellings as aliases.

## Safety

No sizes or concentrations were inferred beyond what the individual official product pages state.
