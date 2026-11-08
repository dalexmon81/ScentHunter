# Paris Corner — Harrier Absolute official product evidence — 8 November 2026

## Verified identity

The brand-owned Paris Corner product page uses the spelling **HARRIER ABSOULTE**, identifies a 100 ml size, and describes the fragrance as one of the brand's EDPs.

Official product page:
https://www.pariscornerperfumes.com/products/harrier-absoulte

## Canonical catalog resolution

The catalog already had the canonical identity `Harrier Absolute` and a second duplicate identity `Harrier Absoulte`. The two records represented the same official product page and the same 100 ml Eau de Parfum variant.

The duplicate `SH-PARIS-CORNER-HARRIER-ABSOULTE` product and its duplicate variant have been consolidated into the existing canonical identity:

- Canonical identity: `Harrier Absolute`
- Official spelling `Harrier Absoulte` retained as an alias
- Size: 100 ml
- Concentration: Eau de Parfum
- Source and evidence URL: the individual official product page above
- Identity status: `source_verified_name`
- One canonical product and one matching variant remain

The registry now has one `Harrier Absolute` row with the official page spelling retained as an alias.

## Regression protection

`backend/tests/test_paris_corner_harrier_absoulte.py` checks the official page, alias mapping, 100 ml EDP variant, and single canonical registry row.
