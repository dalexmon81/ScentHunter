# Paris Corner Pendora registry reconciliation — 8 November 2026

## Harrier Absoulte

The official Paris Corner product page explicitly lists:
- canonical displayed name: HARRIER ABSOULTE;
- size: 100 ml;
- the product copy calls it one of the brand's EDPs.

Official detail page:
https://www.pariscornerperfumes.com/products/harrier-absoulte

The page's navigation places Pendora among the store's product collections, and the product copy refers to "Harrier Pandora". Independent retailer listings also classify it as Pendora Scents, but the catalog uses the official product page as primary evidence and sets `collection_name: "Pendora Scents"` to match the product's existing registry context. One canonical identity and one 100 ml EDP variant are added.

## Attratus / Attractus

The family registry previously contained `Attratus`, while the canonical catalog already contained `Attractus` with a brand-owned individual product page:
https://www.pariscornerperfumes.com/products/attractus

The official all-products collection spells the displayed product name `ATTRACTUS`. This reconciliation treats `Attratus` as a spelling alias of the existing `Attractus` identity, not as a second fragrance. It:
- changes the family-registry canonical row to `Attractus`;
- retains `Attratus` and `Paris Corner Attratus` as aliases;
- adds those aliases to the existing catalog product;
- does not create a duplicate product or variant.

## Snapshot

- Canonical products: 2,074
- Total variants: 332
- Paris Corner canonical identities: 259
- Paris Corner variants: 50

## Regression protection

`backend/tests/test_paris_corner_pendora_registry_fixes.py` checks the official Harrier page, its 100 ml EDP variant, the Attractus alias mapping, and ID uniqueness.
