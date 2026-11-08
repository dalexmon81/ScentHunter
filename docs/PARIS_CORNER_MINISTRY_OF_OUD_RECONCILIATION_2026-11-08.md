# Paris Corner — Ministry of Oud catalog reconciliation — 8 November 2026

## Scope

This change reconciles the 11 Ministry of Oud fragrance identities already present in `backend/family_registry.json` but absent from the canonical product seed.

The brand-owned Paris Corner store's Ministry of Oud collection lists 13 products. Eleven are individual fragrances already represented in the family registry. The other two collection entries are Thailand Oud in Cairo and a 50 ml Signature Set; they are not part of the 11 missing registry identities addressed here. The set is a bundle, not a new canonical fragrance identity.

## Added canonical identities and 100 ml variants

| Canonical identity | Official product page | Concentration |
|---|---|---|
| Ministry of Oud - Amber Oud | https://www.pariscornerperfumes.com/products/ministry-of-oud-amber-oud | Eau de Parfum |
| Ministry of Oud - Oud Indonesian | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-indonesian | Eau de Parfum |
| Ministry of Oud - Oud Royal | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-royal | Eau de Parfum |
| Ministry of Oud - Oud Satin | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-satin | Not stated |
| Ministry of Oud - Strictly Oud | https://www.pariscornerperfumes.com/products/ministry-of-oud-strictly-oud | Eau de Parfum |
| Ministry of Oud Greatest | https://www.pariscornerperfumes.com/products/ministry-of-oud-greatest | Eau de Parfum |
| Ministry of Oud - Gladiators Oath | https://www.pariscornerperfumes.com/products/ministry-of-oud-gladiators-oath | Not stated |
| Ministry of Oud - Maestro's Symphony | https://www.pariscornerperfumes.com/products/ministry-of-oud-maestro-s-symphony | Not stated |
| Ministry of Oud - Nile Whispers | https://www.pariscornerperfumes.com/products/ministry-of-oud-nile-whispers | Not stated |
| Ministry of Oud - Oud Beyond the Wall | https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-beyond-the-wall | Not stated |
| Ministry of Oud - Romance Reverie | https://www.pariscornerperfumes.com/products/ministry-of-oud-romance-reverie | Not stated |

All eleven official detail pages explicitly state a 100 ml size. Concentration is populated only for the five product pages whose official copy explicitly calls the fragrance Eau de Parfum/EDP. For the other six, concentration is deliberately omitted rather than inferred from market convention or third-party listings.

## Catalog changes

- Adds 11 canonical products, each assigned to the existing `paris_corner_catalog` family.
- Adds one 100 ml variant for each canonical product.
- Uses individual brand-owned product pages for both `source_url` and `source_evidence_url`.
- Marks each record `source_verified_name`.
- Updates the existing family-registry rows with `formats_ml: [100]`.
- Does not add prices, offers, stock, or availability.

## Registry discrepancies deliberately not promoted

Two other Paris Corner family-registry names were not added:
- `Attratus`: no matching individual product page was found in the current official Ministry of Oud or main catalog views; the catalog already has the distinct name `Attractus`, so these are not silently merged.
- `Harrier Absoulte`: no matching official product page was found, and the registry spelling may be erroneous. It remains an unresolved discovery record pending stronger evidence.

## Snapshot after this change

- Canonical product identities: 2,073
- Total variants: 331
- Paris Corner canonical identities: 258
- Paris Corner variants: 49

## Regression protection

`backend/tests/test_paris_corner_ministry_of_oud_reconciliation.py` checks all 11 product pages, their 100 ml variants, explicit-only concentration evidence, family-registry alignment, and catalog ID integrity. The existing Paris Corner parity test is updated for the new canonical identity total.
