# Lattafa official new-launch reconciliation — 9 November 2026

Nine previously absent canonical Lattafa fragrance identities were reconciled from individual Lattafa USA product pages.

| Canonical fragrance | Size | Concentration |
|---|---:|---|
| Khamrah Mira | 100 ml | Eau de Parfum |
| Give Me Gourmand Matcha Swirl | 75 ml | Eau de Parfum |
| Beyond Precious | 100 ml | Eau de Parfum |
| Atlas Canyon | 55 ml | Eau de Parfum |
| Give Me Gourmand Harlequin Cream | 75 ml | Eau de Parfum |
| Atlas Glacial Valley | 55 ml | Eau de Parfum |
| Badee Al Oud Amethyst Fusion | 100 ml | Not stated on inspected detail page |
| Raghad | 100 ml | Not stated on inspected detail page |
| Petra Viola | 100 ml | Not stated on inspected detail page |

## Integrity corrections

- All nine names and IDs were absent from the target catalog branch before this patch.
- One explicitly sourced variant was retained per new identity.
- Parent product `formats_ml` was synchronized to the explicit variant size.
- The `lattafa_catalog` family registry now includes all nine products, aliases and matching formats.
- Concentration remains unset for the three pages that did not explicitly state it.

## Validation

Structural checks on the resulting branch: 2,084 canonical products, 412 variants, 124 Lattafa identities; zero duplicate product IDs, duplicate variant IDs, duplicate brand/name pairs, orphan variants, invalid sizes, product/variant size mismatches or missing family entries for these nine additions.

No prices, retailer offers, stock, shipping, GTINs, MPNs or affiliate data were added.
