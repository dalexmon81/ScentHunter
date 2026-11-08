# Paris Corner product-page evidence — 8 November 2026

## Scope

This change verifies four existing Paris Corner identities against individual pages on the brand's official European e-shop, adds four explicit 100 ml variants, and promotes one additional fragrance identity from the existing family registry.

The European shop identifies itself as the **Official e-shop of Paris Corner**. The main brand-owned store separately provides the individual Tiramisu Speculoos page.

## Verified records

| Canonical identity | Public product name | Size | Concentration | Change |
|---|---|---:|---|---|
| Date Caramel | Date Caramel | 100 ml | Eau de Parfum | Existing identity + variant |
| Indomitable | Indomitable | 100 ml | Eau de Parfum | Existing identity + variant |
| Mawj Moscow Mule | Mawj Moscow Mule | 100 ml | Eau de Parfum | Existing identity + variant |
| Perseviron Fig Hug | Fig Hug | 100 ml | Eau de Parfum | Existing identity + alias + variant |
| Tiramisu Speculoos | Tiramisu Speculoos 100ML | 100 ml | Not stated | New identity + size-only variant |

Individual product pages:

- Date Caramel: https://de.pariscornereurope.com/en/products/date-caramel
- Indomitable: https://de.pariscornereurope.com/en/products/indomitable
- Mawj Moscow Mule: https://de.pariscornereurope.com/en/products/paris-corner-mawj-moscow-mule-edp-u-100-ml
- Fig Hug / Perseviron Fig Hug: https://de.pariscornereurope.com/en/products/pc-fig-hug-perseviron-edp-u-100-ml
- Tiramisu Speculoos: https://www.pariscornerperfumes.com/products/tiramisu-speculoos-100ml

## Identity and variant rules

- Fig Hug was already represented by the registry's canonical identity `Perseviron Fig Hug`. The public product name `Fig Hug` is added as an alias, not a duplicate identity.
- Tiramisu Speculoos was present in the family registry but not yet in the canonical product catalog. It is promoted as one new identity with a 100 ml size variant.
- The Tiramisu Speculoos product page establishes the product name and 100 ml size, but does not state EDP or Extrait. Concentration is deliberately omitted.
- Individual product URLs are stored in `source_url` and `source_evidence_url`. Verified names are marked `source_verified_name`.
- The family registry is aligned with the newly confirmed 100 ml sizes.
- No prices, retailer offers, stock, or availability snapshots are copied into the catalog.

## Regression protection

The Paris Corner source-domain test now accepts both the main brand store and the official European e-shop. `backend/tests/test_paris_corner_europe_official_variants.py` checks the four EDP variants, Tiramisu's size-only variant, the Fig Hug alias mapping, family-registry coverage, unique variant IDs, and parent references.

## Snapshot after change

- Total canonical identities: 2,062 (+1)
- Total variants: 320 (+5)
- Paris Corner canonical identities: 247 (+1)
- Paris Corner variants: 38 (+5)
