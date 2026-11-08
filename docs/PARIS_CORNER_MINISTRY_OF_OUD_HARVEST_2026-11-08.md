# Paris Corner — Ministry of Oud official product harvest — 8 November 2026

## Scope

Promotes eleven perfume identities already present in the `paris_corner_catalog` family registry but not yet present in the canonical product catalog. Each identity has an individual product page on the brand-owned Paris Corner store.

All eleven pages explicitly state a 100 ml size. Five pages explicitly identify Eau de Parfum; six do not state the concentration in the retrieved product content. Those six are recorded as size-only variants without inferring EDP or Extrait.

## Verified additions

| Canonical identity | Size | Concentration | Official product page |
|---|---:|---|---|
| Ministry of Oud - Amber Oud | 100 ml | Eau de Parfum | https://www.pariscornerperfumes.com/products/ministry-of-oud-amber-oud |
| Ministry of Oud - Oud Indonesian | 100 ml | Eau de Parfum | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-indonesian |
| Ministry of Oud - Oud Royal | 100 ml | Eau de Parfum | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-royal |
| Ministry of Oud - Oud Satin | 100 ml | Not stated | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-satin |
| Ministry of Oud - Strictly Oud | 100 ml | Eau de Parfum | https://www.pariscornerperfumes.com/products/ministry-of-oud-strictly-oud |
| Ministry of Oud Greatest | 100 ml | Eau de Parfum | https://www.pariscornerperfumes.com/products/ministry-of-oud-greatest |
| Ministry of Oud - Gladiators Oath | 100 ml | Not stated | https://www.pariscornerperfumes.com/products/ministry-of-oud-gladiators-oath |
| Ministry of Oud - Maestro's Symphony | 100 ml | Not stated | https://www.pariscornerperfumes.com/products/ministry-of-oud-maestro-s-symphony |
| Ministry of Oud - Nile Whispers | 100 ml | Not stated | https://www.pariscornerperfumes.com/products/ministry-of-oud-nile-whispers |
| Ministry of Oud - Oud Beyond the Wall | 100 ml | Not stated | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-beyond-the-wall |
| Ministry of Oud - Romance Reverie | 100 ml | Not stated | https://www.pariscornerperfumes.com/products/ministry-of-oud-romance-reverie |

## Data handling

- Existing family-registry canonical names and aliases are reused; no duplicate identity is created.
- Every new product is assigned to `paris_corner_catalog` and marked `source_verified_name`.
- `source_url` and `source_evidence_url` point to the individual brand-owned product page.
- One 100 ml variant is added per identity.
- Concentration is populated only where the page explicitly says Eau de Parfum.
- No prices, retailer offers, stock, or availability data are copied into the catalog.

## Snapshot after this harvest

- Total canonical identities: 2,073
- Total variants: 332
- Paris Corner canonical identities: 258
- Paris Corner variants: 50

## Regression protection

`backend/tests/test_paris_corner_ministry_of_oud_variants.py` checks all eleven product pages, 100 ml formats, explicit versus unspecified concentration, family-registry alignment, unique variant IDs, and valid parent product references.
