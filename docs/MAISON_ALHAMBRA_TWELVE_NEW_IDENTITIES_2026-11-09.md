# Maison Alhambra — twelve additional official EU-store identities — 9 November 2026

## Scope

Adds twelve new Maison Alhambra canonical fragrance identities from individual product pages on Lattafa's European storefront. Each source record explicitly identifies a 100 ml Eau de Parfum. Product IDs and variant IDs are carried from the reviewed source branch; no existing identity is duplicated.

## Added products

| Product | Official page | Size | Concentration |
|---|---|---:|---|
| Dominate Absolu | https://lattafaparfum.eu/de-de/products/dominate-absolu | 100 ml | Eau de Parfum |
| La Rouge Baroque Extreme | https://lattafaparfum.eu/de-de/products/la-rouge-baroque-extreme | 100 ml | Eau de Parfum |
| La Rouge Baroque | https://lattafaparfum.eu/de-de/products/la-rouge-baroque | 100 ml | Eau de Parfum |
| Salvo | https://lattafaparfum.eu/de-de/products/salvo | 100 ml | Eau de Parfum |
| Sugar Me Marshmallow Dream | https://lattafaparfum.eu/de-de/products/sugar-me-marshmallow-dream | 100 ml | Eau de Parfum |
| Jean Lowe Maitre | https://lattafaparfum.eu/de-de/products/jean-lowe-maitre | 100 ml | Eau de Parfum |
| Sugar Me Dulce De Leche | https://lattafaparfum.eu/de-de/products/sugar-me-dulce-de-leche | 100 ml | Eau de Parfum |
| Kismet Magic | https://lattafaparfum.eu/de-de/products/kismet-magic | 100 ml | Eau de Parfum |
| Sugar Me Carrot Cake | https://lattafaparfum.eu/de-de/products/sugar-me-carrot-cake | 100 ml | Eau de Parfum |
| Unknown Deep Woods | https://lattafaparfum.eu/de-de/products/unknown-deep-woods | 100 ml | Eau de Parfum |
| Sugar Me Pistachio Chocolate | https://lattafaparfum.eu/de-de/products/sugar-me-pistachio-chocolate | 100 ml | Eau de Parfum |
| Sugar Me Creme Brulee | https://lattafaparfum.eu/de-de/products/sugar-me-creme-brulee | 100 ml | Eau de Parfum |

## Data changes

- Adds twelve canonical products and their one-to-one 100 ml EDP variants.
- Registers each identity in `maison_alhambra_catalog`.
- Sets individual source, product, and evidence URLs.
- Preserves official GTIN data where present in the reviewed source.
- Adds dedicated regression coverage for product identity, source URL, variant, and family registry parity.
- No prices, stock, shipping, or retailer offers imported.

## Validation

Full catalog seed validation and the dedicated twelve-identity test must pass before review. Draft PR only; no changes to `main`.
