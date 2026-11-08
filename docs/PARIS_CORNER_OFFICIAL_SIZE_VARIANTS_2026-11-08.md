# Paris Corner official size-only variants — 8 November 2026

## Scope

This change adds four 100 ml variant records for existing Paris Corner canonical identities, using individual product pages on the brand-owned Paris Corner store.

The inspected product pages explicitly state the 100 ml size. The retrieved product-page content does not consistently state concentration, so this change deliberately leaves concentration unset rather than inferring Eau de Parfum from the wider product range.

## Verified records

| Existing canonical identity | Official page | Explicit size | Concentration |
|---|---|---:|---|
| Caramel Bash | https://www.pariscornerperfumes.com/products/caramel-bash-1 | 100 ml | Not stated in retrieved page content |
| Dusky Vanilla | https://www.pariscornerperfumes.com/products/dusky-vanilla | 100 ml | Not stated in retrieved page content |
| Fig Fete | https://www.pariscornerperfumes.com/products/fig-fete | 100 ml | Not stated in retrieved page content |
| Khair Peach Delulu | https://www.pariscornerperfumes.com/products/khair-peach-delulu | 100 ml | Not stated in retrieved page content |

## Catalog changes

- Four existing products now point to their individual official product pages in `source_url` and `source_evidence_url`.
- Their identity status is upgraded to `source_verified_name`.
- Four 100 ml variants are added, each retaining the official product URL as evidence.
- Product-level `formats_ml` and the `paris_corner_catalog` family registry are aligned.
- Concentration is intentionally omitted from each new variant.
- No prices, retailer offers, stock, shipping, or availability snapshots are copied.
- No canonical identities are created or removed.

## Snapshot after change

- Total canonical identities: 2,062
- Total variants: 324
- Paris Corner canonical identities: 247
- Paris Corner variants: 42

## Regression protection

`backend/tests/test_paris_corner_official_size_variants.py` checks official product URLs, the 100 ml size, omission of unsupported concentration, family-registry alignment, unique variant IDs, and valid parent product references.
