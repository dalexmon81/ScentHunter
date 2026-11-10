# Paris Corner Europe official-detail integration — 10 November 2026

## Verified products

Eleven existing Paris Corner identities are reconciled against individual pages on the official Paris Corner Europe storefront:

| Product | Size | Concentration |
|---|---:|---|
| Coconut Lagoon | 100 ml | Eau de Parfum |
| Eshal Vanilla | 100 ml | Eau de Parfum |
| Ibisco Nirvana | 65 ml | Eau de Parfum |
| Hurriya | 100 ml | Eau de Parfum |
| Miel Vanille | 100 ml | Eau de Parfum |
| Qissa | 100 ml | Eau de Parfum |
| Fayora | 100 ml | Eau de Parfum |
| Fayora Oshino | 100 ml | Eau de Parfum |
| Qissa Gala | 100 ml | Eau de Parfum |
| Qissa Delicious | 100 ml | Eau de Parfum |
| Qissa Pink | 100 ml | Eau de Parfum |

The individual Europe product-detail URLs are asserted in `backend/tests/test_paris_corner_eleven_official_details.py`.

## Reconciliation

- All eleven canonical product IDs are retained.
- Six new variant records are added.
- Five pre-existing variants are enriched in place; their current variant IDs are preserved.
- Existing discovery/evidence URLs remain intact. The Europe detail pages are recorded separately as `source_product_url`.
- The Paris Corner family registry is synchronized with the explicit sizes and EDP concentration.

## Integrity and safety

No new canonical identities, duplicate variants, or product/size/concentration collisions are introduced. No prices, stock, availability, shipping, retailer offers, GTINs, MPNs or affiliate data are imported.
