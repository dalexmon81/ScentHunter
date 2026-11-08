# Khadlaj La Fede official product harvest — 8 November 2026

## Scope

The `khadlaj_la_fede` family registry already contained 36 fragrance identities. Before this change, only three had canonical product records. The brand-owned Khadlaj Perfumes store's La Fede collections expose individual product-detail pages for the remaining 33 names.

This PR adds those 33 missing canonical identities and one variant for each. It also corrects the source URL of the existing La Fede Intoxicate Mystique record, which previously pointed to the Intoxicate Blue Elixir page by mistake. The two existing Celebrity records are retained without duplicate products or variants.

## Newly added canonical products and variants

| Canonical product | Size | Concentration |
|---|---:|---|
| La Fede Aura Crisp Flower | 100 ml | Eau de Parfum |
| La Fede Aura Kiss of Rose | 100 ml | Eau de Parfum |
| La Fede Aura Manga Splash | 100 ml | Eau de Parfum |
| La Fede Aura Pista Dessert | 100 ml | Eau de Parfum |
| La Fede Bella Reve Dolce Flore | 100 ml | Eau de Parfum |
| La Fede Belle Reve Segrato Viola | 100 ml | Eau de Parfum |
| La Fede Celeste Aqua | 100 ml | Eau de Parfum |
| La Fede Celeste Fluer | 100 ml | Eau de Parfum |
| La Fede Celeste Joice | 100 ml | Eau de Parfum |
| La Fede Celeste Toffee | 100 ml | Eau de Parfum |
| La Fede Choco Brown | 100 ml | Eau de Parfum |
| La Fede Crystallia Imperio | 100 ml | Eau de Parfum |
| La Fede Crystallia Primaso | 100 ml | Eau de Parfum |
| La Fede Edge Intense | 100 ml | Eau de Parfum |
| La Fede Edge Original | 100 ml | Eau de Parfum |
| La Fede First Lady | 75 ml | Eau de Parfum |
| La Fede Intoxicate | 100 ml | Eau de Parfum |
| La Fede Intoxicate Blue Elixir | 100 ml | Eau de Parfum |
| La Fede Kingsman | 75 ml | Eau de Parfum |
| La Fede Lavish Blush | 100 ml | Eau de Parfum |
| La Fede Lavish Luna | 100 ml | Eau de Parfum |
| La Fede Lavish Rouge | 100 ml | Eau de Parfum |
| La Fede Magnum Extreme Blue | 100 ml | Eau de Parfum |
| La Fede Magnum Gold Edition | 100 ml | Eau de Parfum |
| La Fede Magnum Silver Edition | 100 ml | Eau de Parfum |
| La Fede Magnum Wild Green | 100 ml | Eau de Parfum |
| La Fede Miss Premiere | 75 ml | Eau de Parfum |
| La Fede Opera Noir L'Or | 100 ml | Eau de Parfum |
| La Fede Opera Rose L'Or | 100 ml | Eau de Parfum |
| La Fede Statesman | 75 ml | Eau de Parfum |
| La Fede Symbol of Love | 100 ml | Eau de Parfum |
| La Fede Symbol of Power | 100 ml | Eau de Parfum |
| La Fede White Forest Strawberry | 100 ml | Eau de Parfum |

Each new product has its own official product-detail URL stored in `source_url`, `source_evidence_url`, and `source_product_url`. Size and concentration are taken from the individual brand-owned product page or its displayed product title. The 75 ml sizes for First Lady, Kingsman, Miss Premiere, and Statesman are preserved as distinct formats.

## Existing records reconciled

- `La Fede Celebrity Crush` — existing 100 ml EDP record retained.
- `La Fede Celebrity Fame` — existing 100 ml EDP record retained.
- `La Fede Intoxicate Mystique` — existing 100 ml Extrait record retained; its source URL is corrected to its own official product page rather than the Intoxicate Blue Elixir page.

## Catalog changes

- Adds 33 canonical products to the existing `khadlaj_la_fede` family.
- Adds 33 matching variants.
- Preserves the three existing La Fede canonical products and their variants.
- Updates the La Fede registry's format sizes and adds the spelling alias `La Fede Celeste Fleur` to the canonical `La Fede Celeste Fluer` record because the official page title spells it "Fleur" while the collection card and URL use "Fluer".
- No prices, offers, stock, or availability data are copied.

## Snapshot after change

- Total canonical products: 2,107
- Total variants: 365
- Khadlaj canonical products: 149
- La Fede canonical products: 36
- La Fede variants: 36

## Regression protection

`backend/tests/test_khadlaj_la_fede.py` now checks all 36 registry identities, their individual official product pages, sizes, concentrations, family-registry formats, and unique product/variant IDs.
