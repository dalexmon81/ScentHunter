# Paris Corner — Ministry of Oud official harvest — 8 November 2026

## Scope and source

The brand-owned Paris Corner storefront has a dedicated Ministry of Oud collection showing 13 products. The collection includes both individual fragrances and a 50 ml signature set. This pass adds only the 11 missing individual fragrance identities already present in the Paris Corner family registry; it does not import the gift set or create duplicates for products already in the catalog.

Official collection:
https://www.pariscornerperfumes.com/collections/ministry-of-oud

## Eleven individual fragrances added

All 11 individual brand product pages explicitly show 100 ml.

| Canonical identity | Official product page | Concentration on page |
|---|---|---|
| Ministry of Oud - Amber Oud | https://www.pariscornerperfumes.com/products/ministry-of-oud-amber-oud | Eau de Parfum |
| Ministry of Oud - Gladiators Oath | https://www.pariscornerperfumes.com/products/ministry-of-oud-gladiators-oath | Not stated |
| Ministry of Oud - Maestro's Symphony | https://www.pariscornerperfumes.com/products/ministry-of-oud-maestro-s-symphony | Not stated |
| Ministry of Oud - Nile Whispers | https://www.pariscornerperfumes.com/products/ministry-of-oud-nile-whispers | Not stated |
| Ministry of Oud - Oud Beyond the Wall | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-beyond-the-wall | Not stated |
| Ministry of Oud - Oud Indonesian | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-indonesian | Eau de Parfum |
| Ministry of Oud - Oud Royal | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-royal | Eau de Parfum |
| Ministry of Oud - Oud Satin | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-satin | Not stated |
| Ministry of Oud - Romance Reverie | https://www.pariscornerperfumes.com/products/ministry-of-oud-romance-reverie | Not stated |
| Ministry of Oud - Strictly Oud | https://www.pariscornerperfumes.com/products/ministry-of-oud-strictly-oud | Eau de Parfum |
| Ministry of Oud Greatest | https://www.pariscornerperfumes.com/products/ministry-of-oud-greatest | Eau de Parfum |

## Catalog changes

- Adds 11 canonical product records and 11 matching 100 ml variants.
- Preserves the names already held by `paris_corner_catalog` in the family registry.
- Stores each individual brand-owned product page in both `source_url` and `source_evidence_url`.
- Marks the 11 names as `source_verified_name`.
- Sets 100 ml for every record because each individual page explicitly states that size.
- Sets concentration only where the individual page explicitly identifies Eau de Parfum: Amber Oud, Oud Indonesian, Oud Royal, Strictly Oud, and Ministry of Oud Greatest.
- Leaves concentration absent for Gladiators Oath, Maestro's Symphony, Nile Whispers, Oud Beyond the Wall, Oud Satin, and Romance Reverie. Their product pages show size and fragrance notes, but do not explicitly state concentration in the retrieved detail content.
- Adds no prices, retailer offers, stock, shipping, or availability data.

## Additional legacy-name reconciliation

- The family registry contained the misspelling `Attratus`; the official Pendora Scents collection and individual brand page show `Attractus`. The typo is now an alias of the existing Attractus canonical identity, not a separate product.
- The registry also contained `Harrier Absoulte`; the existing canonical identity is `Harrier Absolute`. The typo is now an alias of that existing record. Its current catalog evidence remains the brand's general collection listing; no individual official product page was located, so its source confidence is not upgraded.

## Deliberate exclusions

- The 50 ml Signature Set is a multi-fragrance gift set, not a single canonical fragrance identity.
- Thailand Oud in Cairo already has a separate catalogue status and was not part of this registry gap.

## Snapshot after change

- Total canonical identities: 2,073
- Total variants: 331
- Paris Corner canonical identities: 258
- Paris Corner variants: 49

## Regression protection

`backend/tests/test_paris_corner_ministry_of_oud_official_harvest.py` verifies all 11 official detail URLs, 100 ml variants, family-registry format alignment, concentration omissions where the source is silent, unique variant IDs, and valid parent product references.
