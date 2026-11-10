# Khadlaj final official product-page reconciliation — 10 November 2026

## Result

Eight remaining existing Khadlaj identities were checked against individual official product pages. Seven new size variants were added; Shahi Oud already had a verified variant and was preserved unchanged.

| Product | Size | Concentration | GTIN |
|---|---:|---|---|
| Sawaar Vanille Blanc | 100 ml | Unresolved on official page | 6298043070768 |
| Maison L'Imaginaire | 100 ml | Eau de Parfum | 6291107976044 |
| Saqr Al Badiya | 100 ml | Unresolved on official page | 6291107978765 |
| Musk Pure Musk Blend Creation of Iqbal | 60 ml | Eau de Parfum | 6291107978154 |
| Wild Indonesian Oud | 60 ml | Eau de Parfum | 6291107974620 |
| Shahi Oud | 100 ml | Eau de Parfum | 6291107971032 |
| Barwaaz Solid Grey | 100 ml | Eau de Parfum | 6291107974392 |
| Musk Couture | 100 ml | Eau de Parfum | 6291107976976 |

## First-party evidence

- Sawaar Vanille Blanc: https://khadlaj-perfumes.com/products/sawaar-vanille-blanc-100-ml-eau-de-parfum-spray-for-women
- Maison L'Imaginaire: https://khadlaj-perfumes.com/collections/premium-colllection/products/maison-l-imaginaire-100ml-edp-spray
- Saqr Al Badiya: https://khadlaj-perfumes.com/products/saqr-al-badiya-extrait-de-parfum-spray-for-men-with-aquatic-notes-shop-online-dubai-uae
- Musk Pure Musk Blend Creation of Iqbal: https://khadlaj-perfumes.com/products/musk-pure-musk-blend-creation-of-iqbal-65-ml-edp-spray-perfume-for-men-and-women-online-dubai-uae
- Wild Indonesian Oud: https://khadlaj-perfumes.com/products/wild-indonesian-oud-spray-shop-online-best-price-in-dubai-uae
- Shahi Oud: https://khadlaj-perfumes.com/products/shahi-oud-edp-spray-shop-online-best-price-in-dubai-uae
- Barwaaz Solid Grey: https://khadlaj-perfumes.com/products/barwaaz-solid-grey-spray-shop-online-best-price-in-dubai-uae
- Musk Couture: https://khadlaj-perfumes.com/collections/unisex-1/products/musk-couture-edp-spray-100-ml-best-perfume-for-men-and-women-in-dubai-uae

## Deliberate data-quality decisions

- Sawaar Vanille Blanc: the official page identifies 100 ml and GTIN 6298043070768, but the page title says Eau de Parfum while product imagery says Extrait de Parfum. Size and GTIN are recorded; concentration is deliberately left unset.
- Saqr Al Badiya: the official page title says Extrait de Parfum while the product description says Eau de Parfum. Size and GTIN are recorded; concentration is deliberately left unset.
- Musk Pure Musk Blend Creation of Iqbal: the official URL slug contains 65 ml, but the product title and size selector both show 60 ml. The variant records 60 ml.
- Wild Indonesian Oud: the official product page names the product “Wild Indonesian Oud Pure”; the existing canonical identity is retained and its aliases already cover the official name.

## Catalog changes

- Reused the eight existing canonical product IDs.
- Upgraded identity status and stored official product-page provenance.
- Added one explicit size variant for the seven products without one; the existing Shahi Oud variant was preserved unchanged.
- Preserved unknown concentrations where official page fields conflict; no guess was made.
- Added GTINs only as displayed on the official pages.
- Updated the existing family-registry rows.
- No prices, stock, availability, shipping, or retailer-offer data imported.

## Regression coverage

`backend.tests.test_khadlaj_official_spray_fourth_followup` checks canonical identity, source provenance, one variant per product, size, GTIN, family-registry alignment, and that conflicting concentrations remain unset.
