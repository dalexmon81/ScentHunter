# Mykonos variant evidence — 8 November 2026

## Scope

This change adds explicit size/concentration variants to 16 existing Mykonos canonical identities. It creates no new canonical perfume identities and does not change prices, offers, stock, or retailer availability.

The brand-owned Indonesian storefront remains recorded in each product's `source_url`:
- https://officialmykonos.com/collections/all

For the exact variant attributes, the catalog now records `source_evidence_url` pointing to an individual product page on Mykonos EU. The retailer explicitly identifies itself as an authorized MYKONOS retailer for Europe and says the products are crafted in Indonesia by MYKONOS. It also explicitly states that it is not the official Mykonos site. Therefore these URLs are treated as **authorized-retailer secondary evidence**, not as manufacturer-owned URLs.

## Verified variants

| Existing identity | Size | Concentration | Individual evidence |
|---|---:|---|---|
| Only You | 100 ml | Eau de Parfum | https://mykonosperfumes.eu/products/mykonos-only-you |
| Shades Perfume | 100 ml | Not stated | https://mykonosperfumes.eu/products/mykonos-shades |
| Chai Crema Latte | 50 ml | Extrait de Parfum | https://mykonosperfumes.eu/products/mykonos-x-sapeyeeee-chai-crema-latte |
| Jynx | 100 ml | Eau de Parfum | https://mykonosperfumes.eu/products/mykonos-x-paola-serena-jynx |
| Rouge | 50 ml | Eau de Parfum | https://mykonosperfumes.eu/products/mykonos-x-sapeyeeee-rouge |
| Seven Roses | 50 ml | Eau de Parfum | https://mykonosperfumes.eu/products/mykonos-seven-roses |
| Ivory | 50 ml | Eau de Parfum | https://mykonosperfumes.eu/products/mykonos-ivory |
| Blossom | 50 ml | Eau de Parfum | https://mykonosperfumes.eu/products/mykonos-blossom |
| Zora | 50 ml | Eau de Parfum | https://mykonosperfumes.eu/products/mykonos-zora |
| Zora | 100 ml | Eau de Parfum | https://mykonosperfumes.eu/products/mykonos-zora |
| Down to Earth | 50 ml | Extrait de Parfum | https://mykonosperfumes.eu/products/mykonos-down-to-earth |
| When in Paris | 50 ml | Extrait de Parfum | https://mykonosperfumes.eu/products/mykonos-when-in-paris |
| Pandan Sticky Rice | 50 ml | Eau de Parfum | https://mykonosperfumes.eu/products/mykonos-pandan-sticky-rice |
| Pistachio Cream Cake | 50 ml | Eau de Parfum | https://mykonosperfumes.eu/products/mykonos-pistachio-cream-cake |
| Blaze | 50 ml | Eau de Parfum | https://mykonosperfumes.eu/products/mykonos-blaze |
| Memoir of Meri | 50 ml | Extrait de Parfum | https://mykonosperfumes.eu/products/mykonos-x-jumbo-memoir-of-meri |
| Once Upon Don | 50 ml | Extrait de Parfum | https://mykonosperfumes.eu/products/mykonos-x-jumbo-once-upon-don |

**Important:** Shades Perfume is intentionally recorded without a concentration. Its individual retailer page says that Mykonos does not state whether it is EDP or Extrait. No concentration has been inferred.

## Source-quality notes

- The product pages are individual SKU-level pages, not merely a collection listing.
- The retailer identifies itself as authorized for Europe and identifies Mykonos as the maker.
- The retailer pages are not a substitute for manufacturer confirmation. If the manufacturer later publishes conflicting regional information, review the variant and preserve both source records.
- Prices and stock text visible on retailer pages are deliberately not copied into the catalog.

## Regression protection

`backend/tests/test_mykonos_authorized_retailer_variants.py` checks:
- all 16 existing canonical identities are retained;
- the 17 documented size/concentration combinations are present;
- individual product evidence URLs are preserved separately from the brand-owned collection URL;
- Shades remains without an inferred concentration;
- variant IDs remain unique.
