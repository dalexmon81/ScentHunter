# Paris Corner Harrier and Ministry of Oud official harvest — 8 November 2026

## Scope

This pass reconciles twelve existing family-registry entries to individual product pages on the Paris Corner brand-owned storefront:
- Harrier Absoulte
- Eleven Ministry of Oud fragrances

Twelve canonical product identities and twelve 100 ml variants are added. The registry typo `Attratus` is reconciled as an alias of the already existing canonical identity `Attractus`; no duplicate product is created.

The brand-owned Ministry of Oud collection page reports 13 products. The collection includes a 50 ml signature gift set and Thailand Oud in Cairo, which are not imported by this change because the current family-registry gap list did not identify them as missing canonical perfume identities. A gift set is not treated as a standalone fragrance identity.

## Official product pages

| Canonical identity | Official product page | Size | Concentration |
|---|---|---:|---|
| Harrier Absoulte | https://www.pariscornerperfumes.com/products/harrier-absoulte | 100 ml | Eau de Parfum |
| Ministry of Oud - Amber Oud | https://www.pariscornerperfumes.com/products/ministry-of-oud-amber-oud | 100 ml | Eau de Parfum |
| Ministry of Oud - Gladiators Oath | https://www.pariscornerperfumes.com/products/ministry-of-oud-gladiators-oath | 100 ml | Not explicitly stated |
| Ministry of Oud - Maestro's Symphony | https://www.pariscornerperfumes.com/products/ministry-of-oud-maestro-s-symphony | 100 ml | Not explicitly stated |
| Ministry of Oud - Nile Whispers | https://www.pariscornerperfumes.com/products/ministry-of-oud-nile-whispers | 100 ml | Not explicitly stated |
| Ministry of Oud - Oud Beyond the Wall | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-beyond-the-wall | 100 ml | Not explicitly stated |
| Ministry of Oud - Oud Indonesian | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-indonesian | 100 ml | Eau de Parfum |
| Ministry of Oud - Oud Royal | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-royal | 100 ml | Eau de Parfum |
| Ministry of Oud - Oud Satin | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-satin | 100 ml | Not explicitly stated |
| Ministry of Oud - Romance Reverie | https://www.pariscornerperfumes.com/products/ministry-of-oud-romance-reverie | 100 ml | Not explicitly stated |
| Ministry of Oud - Strictly Oud | https://www.pariscornerperfumes.com/products/ministry-of-oud-strictly-oud | 100 ml | Eau de Parfum |
| Ministry of Oud Greatest | https://www.pariscornerperfumes.com/products/ministry-of-oud-greatest | 100 ml | Eau de Parfum |

## Evidence rules

- Every added record uses an individual page on `pariscornerperfumes.com` as both `source_url` and `source_evidence_url`.
- Every added product is marked `source_verified_name`.
- All twelve pages explicitly show a 100 ml size.
- Concentration is populated only for pages whose product description explicitly identifies Eau de Parfum / EDP. The other six records intentionally omit concentration.
- No prices, offers, retailer stock, shipping, or availability are imported.
- `Attratus` is retained as an alias of official product `Attractus`, not a separate identity.

## Catalog snapshot after this change

- Canonical identities: 2,074
- Variants: 332
- Paris Corner canonical identities: 259
- Paris Corner variants: 50

## Regression protection

`backend/tests/test_paris_corner_ministry_of_oud_official_harvest.py` checks all twelve official product URLs, 100 ml variants, the evidence-based concentration rule, family-registry size alignment, unique variant IDs, and the `Attratus` → `Attractus` alias reconciliation.
