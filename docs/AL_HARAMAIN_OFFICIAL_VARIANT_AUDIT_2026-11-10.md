# Al Haramain official variant audit — 10 November 2026

## Scope

Seven Al Haramain bottle variants were reconciled against individual product pages on the brand's official EU storefront. Existing canonical product IDs are reused.

## Verified variants

| Existing canonical product | Format | Concentration | Official product page |
|---|---:|---|---|
| Amber Oud Bleu Edition | 60 ml | Eau de Parfum | https://shop.alharamainperfumes.com/eu/amber-oud-bleu-edition.html |
| Amber Oud Bleu Edition | 200 ml | Eau de Parfum | https://shop.alharamainperfumes.com/eu/amber-oud-bleu-edition-200ml.html |
| Amber Oud Tobacco Edition | 100 ml | Eau de Parfum | https://shop.alharamainperfumes.com/eu/amber-oud-tobacco-100ml.html |
| L'Aventure Femme | 30 ml | Eau de Parfum | https://shop.alharamainperfumes.com/eu/al-haramain-l-aventure-femme-30ml.html |
| L'Aventure Femme | 100 ml | Eau de Parfum | https://shop.alharamainperfumes.com/eu/haramain-l-aventure-femme-100ml-eau-de-parfum.html |
| Junoon | 75 ml | Eau de Parfum | https://shop.alharamainperfumes.com/eu/haramain-junoon.html |
| Black Oud | 100 ml | Extrait de Parfum | https://shop.alharamainperfumes.com/eu/haramain-black-oud-spray-100ml.html |

## Identifier handling

The official pages expose Al Haramain stock-keeping units (for example, AHP1016 and AHP1002), but these are SKUs, not GTIN/EAN barcodes. No GTIN was exposed in the product-page content, so the catalog's GTIN fields remain empty.

## Deliberate exclusions

- Floral Fair was not updated: the official product page headline calls it Extrait de Parfum, while its details section labels the type Eau de Parfum. The concentration conflict must be resolved before a variant can be safely recorded.
- No price, stock, availability, shipping or retailer-offer data is copied into the canonical catalog.

## Catalog changes

- Reuse existing Al Haramain product IDs.
- Add the seven explicitly documented size/concentration variants.
- Align the corresponding formats in the existing al_haramain_catalog family-registry entry.
- Preserve the pre-existing 200 ml Amber Oud Tobacco Edition variant.

## Regression coverage

`backend.tests.test_al_haramain_official_variants_2026_11_10` verifies canonical IDs, official source URLs, variant IDs, formats, concentrations, family-registry alignment, uniqueness, parent links and separation from offer data.
