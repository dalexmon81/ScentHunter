# Paris Corner Ministry of Oud and spelling reconciliation — 8 November 2026

## Scope

This pass audited the Ministry of Oud family and two spelling discrepancies in the Paris Corner family registry. It does not add new Ministry of Oud canonical identities: all 11 fragrance identities listed below were already present in `backend/product_catalog.json`, each with an individual brand-owned product page and a 100 ml variant.

The official Ministry of Oud collection currently lists 13 items. The 11 individual fragrances overlap with existing catalog identities; the remaining entries include Thailand Oud in Cairo (already cataloged) and a 50 ml signature set (a set, not a new single-fragrance canonical identity).

## Ministry of Oud verification

The official brand collection: https://www.pariscornerperfumes.com/collections/ministry-of-oud

Individual official pages:

- Amber Oud: https://www.pariscornerperfumes.com/products/ministry-of-oud-amber-oud
- Oud Indonesian: https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-indonesian
- Oud Royal: https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-royal
- Oud Satin: https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-satin
- Strictly Oud: https://www.pariscornerperfumes.com/products/ministry-of-oud-strictly-oud
- Greatest: https://www.pariscornerperfumes.com/products/ministry-of-oud-greatest
- Gladiators Oath: https://www.pariscornerperfumes.com/products/ministry-of-oud-gladiators-oath
- Maestro's Symphony: https://www.pariscornerperfumes.com/products/ministry-of-oud-maestro-s-symphony
- Nile Whispers: https://www.pariscornerperfumes.com/products/ministry-of-oud-nile-whispers
- Oud Beyond the Wall: https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-beyond-the-wall
- Romance Reverie: https://www.pariscornerperfumes.com/products/ministry-of-oud-romance-reverie

The existing regression test `test_paris_corner_ministry_of_oud_variants.py` already checks the 11 individual pages, 100 ml variants, and the concentration only where the official page explicitly states it. This pass preserves that conservative rule: no concentration is inferred from collection membership alone.

## Spelling reconciliation

### Attratus → Attractus

The family registry had a separate `Attratus` row, while the catalog and the brand-owned individual page use `Attractus`. The spelling variant is now an alias on the existing Attractus identity. No second product is created.

Official page: https://www.pariscornerperfumes.com/products/attractus

### Harrier Absoulte → Harrier Absolute

The official brand page is titled `HARRIER ABSOULTE` and states 100 ml. The catalog already had the canonical identity `Harrier Absolute`. The official spelling is now an alias of that existing identity; the registry duplicate row is consolidated into the canonical row.

Official page: https://www.pariscornerperfumes.com/products/harrier-absoulte

The same page states 100 ml and describes the fragrance as one of the brand's EDPs. The existing Harrier Absolute record now points to this detail page and has one 100 ml Eau de Parfum variant. The official page's spelling is preserved as an alias rather than used as a second canonical identity.

## Catalog and registry changes

- No Ministry of Oud canonical identity is duplicated or newly created.
- The two spelling discrepancies are consolidated as aliases.
- The existing Harrier Absolute record is linked to its individual official detail page and its 100 ml EDP variant is represented.
- The Paris Corner family registry no longer has separate canonical rows for Attratus or Harrier Absoulte.
- No price, offer, stock, or availability data is added.

## Regression protection

- `backend/tests/test_paris_corner_ministry_of_oud_variants.py` covers the existing Ministry of Oud identities and their evidence.
- `backend/tests/test_paris_corner_harrier_absoulte.py` now verifies the official spelling as an alias of Harrier Absolute.
- `backend/tests/test_paris_corner_spelling_reconciliation.py` checks the Attratus alias, Harrier alias, and registry uniqueness.
