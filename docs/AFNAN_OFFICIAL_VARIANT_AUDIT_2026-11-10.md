# Afnan official variant audit — 10 November 2026

## Scope

This follow-up reconciles thirteen existing Afnan canonical identities against individual product pages on Afnan's official regional storefronts. Existing product IDs are reused; no duplicate canonical products are added.

## Official product-page evidence

| Product | Official product page | Type | Volume | Audience |
|---|---|---|---:|---|
| 9 AM Dive | https://www.de.afnan.com/en/products/9-am-dive | Eau de Parfum | 100 ml | Unisex |
| Rare Reef | https://www.at.afnan.com/en/products/rare-reef | Extrait de Parfum | 100 ml | Unisex |
| Turathi Brown Homme | https://www.at.afnan.com/en/products/turathi-brown-homme | Eau de Parfum | 90 ml | Pour Homme |
| Historic Olmeda | https://www.at.afnan.com/products/historic-olmeda | Eau de Parfum | 100 ml | Pour Homme |
| Mystique Bouquet | https://www.de.afnan.com/en/products/mystique-bouquet | Eau de Parfum | 80 ml | Pour Femme |
| Supremacy Pink | https://www.fr.afnan.com/products/supremacy-pink | Eau de Parfum | 100 ml | Pour Femme |
| Rare Carbon | https://www.at.afnan.com/en/products/rare-carbon | Eau de Parfum | 100 ml | Pour Homme |
| Turathi Blue | https://www.fr.afnan.com/products/turathi-blue-homme | Eau de Parfum | 90 ml | Pour Homme |
| Souvenir Floral Bouquet | https://at.afnan.com/en/products/souvenir-floral-bouquet | Eau de Parfum | 100 ml | Pour Femme |
| Supremacy Gala | https://www.at.afnan.com/en/products/supremacy-gala | Extrait de Parfum | 90 ml | Pour Femme |
| 9 PM Rebel | https://www.at.afnan.com/en/products/9-pm-rebel | Eau de Parfum | 100 ml | Unisex |
| 9 PM Elixir | https://www.fr.afnan.com/products/9-pm-elixir | Extrait de Parfum | 100 ml | Unisex |
| Supremacy Purple | https://saudi.afnan.com/products/supremacy-purple | Eau de Parfum | 100 ml | Pour Femme |

The official pages explicitly expose type and volume in their product detail sections. No GTIN/EAN/barcode was exposed in the retrieved official page content, so no GTIN is added.

## Catalog changes

- Reuse the thirteen existing Afnan canonical product IDs.
- Upgrade the source-listed identities to source-verified names; keep previously verified names verified.
- Add one variant per official size and concentration.
- Add the matching format to each existing Afnan family-registry entry.
- Preserve all existing product and variant IDs outside this batch.
- Do not import price, stock, availability, shipping or retailer-offer data.

## Regression coverage

`backend.tests.test_afnan_official_variants_2026_11_10` checks the thirteen canonical IDs, product-page provenance, size, concentration, variant IDs, family-registry formats, unique IDs/GTINs/variant tuples, parent links and separation from commercial offer data.
