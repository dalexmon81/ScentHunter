# Paris Corner — Harrier Absoulte official spelling reconciliation — 8 November 2026

## Official evidence

The brand-owned Paris Corner product page is titled **HARRIER ABSOULTE** and identifies the bottle as 100 ml. Its product description explicitly calls it one of the brand's EDPs.

Official product page:
https://www.pariscornerperfumes.com/products/harrier-absoulte

## Canonical mapping

The catalog already contains the canonical identity `Harrier Absolute`. This change preserves that existing product ID and canonical name, while adding the official spelling `Harrier Absoulte` and the prefixed spelling as aliases.

This avoids creating two canonical products for a spelling difference while keeping the brand's exact displayed spelling searchable.

## Catalog changes

- Existing product ID retained: `SH-PARIS-CORNER-HARRIER-ABSOLUTE`.
- `source_url` and `source_evidence_url` now point to the individual official product page.
- Identity status upgraded to `source_verified_name`.
- 100 ml size and Eau de Parfum concentration recorded.
- Exactly one 100 ml EDP variant linked to the existing canonical product.
- Family registry retains one `Harrier Absolute` row, with `Harrier Absoulte` as an alias; the duplicate typo row is removed.

## Deliberate exclusion

The separate family-registry entry `Attratus` is not merged into `Attractus`. The current official page spells the latter as `Attractus`; a similar name alone is not enough to prove they are the same product.

## Regression protection

`backend/tests/test_paris_corner_harrier_absoulte_alias.py` checks the official page, preserved canonical ID, alias mapping, 100 ml EDP variant, and uniqueness of family-registry canonical names.
