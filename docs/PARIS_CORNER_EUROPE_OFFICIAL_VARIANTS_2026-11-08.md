# Paris Corner Europe product-page evidence — 8 November 2026

## Scope

This change verifies four existing Paris Corner catalog identities against individual pages on the brand's official European e-shop. It adds four explicit 100 ml Eau de Parfum variants. No canonical identities are created or removed.

The European shop identifies itself as the **Official e-shop of Paris Corner**. Its product page identifies Fig Hug as an EDP in 100 ml and describes it as "Perseviron Fig Hug". The catalog already had the canonical identity `Perseviron Fig Hug`; this change adds `Fig Hug` and `Paris Corner Fig Hug` as aliases rather than creating a second identity.

## Verified records

| Existing canonical identity | Public product name | Size | Concentration |
|---|---|---:|---|
| Date Caramel | Date Caramel | 100 ml | Eau de Parfum |
| Indomitable | Indomitable | 100 ml | Eau de Parfum |
| Mawj Moscow Mule | Mawj Moscow Mule | 100 ml | Eau de Parfum |
| Perseviron Fig Hug | Fig Hug | 100 ml | Eau de Parfum |

Individual official European product pages:

- Date Caramel: https://de.pariscornereurope.com/en/products/date-caramel
- Indomitable: https://de.pariscornereurope.com/en/products/indomitable
- Mawj Moscow Mule: https://de.pariscornereurope.com/en/products/paris-corner-mawj-moscow-mule-edp-u-100-ml
- Fig Hug / Perseviron Fig Hug: https://de.pariscornereurope.com/en/products/pc-fig-hug-perseviron-edp-u-100-ml

## Catalog changes

- `source_url` and `source_evidence_url` now point to the individual official EU product page for each record.
- All four existing identities are marked `source_verified_name`.
- Each product has `formats_ml: [100]` and `concentration: "Eau de Parfum"`.
- Four matching variant records are added.
- The existing family-registry row for Perseviron Fig Hug is retained and aligned to 100 ml.
- No prices, retailer offers, stock, or availability snapshots are copied into the catalog.

## Snapshot after change

- Total canonical identities: 2,061 (unchanged)
- Total variants: 319
- Paris Corner canonical identities: 246 (unchanged)
- Paris Corner variants: 37

## Regression protection

`backend/tests/test_paris_corner_europe_official_variants.py` checks official product URLs, the 100 ml EDP variants, family-registry alignment, unique variant IDs, and the Fig Hug alias mapping to the existing Perseviron Fig Hug identity.
