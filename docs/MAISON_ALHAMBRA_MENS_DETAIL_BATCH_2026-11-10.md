# Maison Alhambra men's official detail-page batch — 10 November 2026

## Scope

Seven standalone men's fragrances were reconciled from individual product pages on the Maison Alhambra USA storefront. Each included page shows the product name, Eau de Parfum designation, 3.4 oz / 100 ml size and barcode.

- Two existing canonical identities are upgraded in place: Galactic Men Intense and Jorge di Profumo.
- Five new canonical identities are added: Yeah, Yeah! Man Parfum, Toro Pour Homme Glace, Your Touch Amber and Opulence Leather.
- Each receives one 100 ml Eau de Parfum variant.
- Existing product IDs are preserved; only the five absent brand/name identities receive new IDs.
- GTINs are copied only from their matching official detail pages.

## Official detail evidence

| Canonical product | Size | Concentration | GTIN | Official product page |
|---|---:|---|---|---|
| Galactic Men Intense | 100 ml | Eau de Parfum | 6290362340515 | https://maisonalhambra-usa.com/collections/fragrances-for-him/products/maison-alhambra-galactic-men-intense-eau-de-parfum-for-men |
| Jorge di Profumo | 100 ml | Eau de Parfum | 6291108730140 | https://maisonalhambra-usa.com/collections/fragrances-for-him/products/maison-alhambra-jorge-di-profumo-eau-de-parfum-for-men |
| Yeah | 100 ml | Eau de Parfum | 6291108730324 | https://maisonalhambra-usa.com/collections/fragrances-for-him/products/maison-alhambra-yeah-eau-de-parfum-for-men |
| Yeah! Man Parfum | 100 ml | Eau de Parfum | 6290360590745 | https://maisonalhambra-usa.com/collections/fragrances-for-him/products/maison-alhambra-yeah-man-parfum-eau-de-parfum-for-men |
| Toro Pour Homme Glace | 100 ml | Eau de Parfum | 6290362340942 | https://maisonalhambra-usa.com/collections/fragrances-for-him/products/maison-alhambra-toro-pour-homme-glace-eau-de-parfum-for-men |
| Your Touch Amber | 100 ml | Eau de Parfum | 6290362340973 | https://maisonalhambra-usa.com/collections/fragrances-for-him/products/maison-alhambra-your-touch-amber-eau-de-parfum-for-men |
| Opulence Leather | 100 ml | Eau de Parfum | 6291108730041 | https://maisonalhambra-usa.com/collections/fragrances-for-him/products/maison-alhambra-opulence-leather-eau-de-parfum-for-men |

## Deliberate exclusion

Maitre de Blue is not upgraded in this batch. Its official page title says “Maitre De Blue”, while the page description refers to “Blue de Chance”. This mismatch requires a separate brand-identity reconciliation before assigning the page's size, concentration and barcode to the existing Maitre de Blue identity. The catalog record remains unchanged.

## Data safeguards

- No prices, stock, availability, shipping, retailer offers or affiliate fields are imported.
- No existing product or variant IDs are regenerated.
- Existing family ID `maison_alhambra_catalog` is reused.
- The requested-brand regression floor rises from 226 to 237 canonical identities.
- Search and offer-ingestion behavior are unchanged.
