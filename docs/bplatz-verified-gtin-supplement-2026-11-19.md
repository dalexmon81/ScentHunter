# Bplatz verified canonical GTIN supplement — 19 November 2026

This supplement adds eight Bplatz product identities to the isolated catalog. Each entry has a Bplatz staged observation with the same GTIN, brand, 100 ml size and Eau de Parfum concentration, plus independent product-source corroboration.

| Canonical product | GTIN-13 | Independent corroboration |
|---|---:|---|
| Ard Al Zaafaran Thara Al Oud | 6435074242867 | ScentArabia; Unpuf |
| Maison Alhambra Chic Velvet Vert Secret | 6290360590707 | ScentCompare; Maison des Fragrances |
| Al Fares Hajes Flame | 6294021907668 | Tienda Lafe; Joyasshirel |
| Lattafa Sehr | 6290360599090 | Lattafa official; Shop Apotheke |
| Milestone Hayati Marshmallow | 6294021904742 | Qogita |
| Milestone Alvina Desira | 6294021906661 | ScentArabia; Shure Cosmetics |
| Milestone Perfume Blast Infrared | 6294021907019 | Shure Cosmetics |
| Milestone Perfume Blast Confident | 6294021907002 | Shure Cosmetics |

## Matching safeguards

- Each GTIN has a check-digit-valid GTIN-13 mapping to one canonical product and one 100 ml variant.
- The Bplatz display title “Very” is retained as an alias for canonical Lattafa Sehr; the GTIN and independent product sources identify the canonical name as Sehr.
- Matching requires the verified GTIN, brand, size and concentration checks to agree.
- The supplement does not create an offer by itself. Pending Bplatz observations are promoted only by the separate guarded backfill workflow.
- No fuzzy or cross-brand matching is enabled.

## Validation

The regression suite verifies all 21 reviewed Bplatz GTIN mappings (13 previous entries plus these eight). The canonical catalog seed dry-run validates the base catalog and supplement without writing to the database.
