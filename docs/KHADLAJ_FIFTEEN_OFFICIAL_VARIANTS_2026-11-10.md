# Khadlaj official product-page reconciliation — 10 November 2026

## Result

Fifteen existing Khadlaj canonical identities were checked against individual official product pages. Twelve new explicit variants were added; the three existing variants for Oud Pour Noble, Musk Al Sabah, and Oud Al Sabah were preserved unchanged.

| Product | Size | Concentration | GTIN |
|---|---:|---|---|
| Cashmere Warm Oud | 100 ml | Eau de Parfum | 6291107974781 |
| Cashmere Sunshine Musk | 100 ml | Eau de Parfum | 6291107974798 |
| Ghadeer Silver | 100 ml | Eau de Parfum | 6291107977010 |
| Infini Absolute | 100 ml | Eau de Parfum | 6291107975481 |
| Sensuous Night | 100 ml | Eau de Parfum | Not provided on the inspected official page |
| Oud Pour Noble | 100 ml | Eau de Parfum | 6291107971025 |
| Oud Pour Shaikh | 100 ml | Eau de Parfum | 6291107970608 |
| Oud Pour Rouge | 100 ml | Eau de Parfum | Not provided on the inspected official page |
| Rose Couture | 100 ml | Eau de Parfum | Not provided on the inspected official page |
| Musk Pour Narcis | 100 ml | Eau de Parfum | 6291107970592 |
| Oud Pour Blueberry | 100 ml | Eau de Parfum | Not provided on the inspected official page |
| Magnate Noble | 100 ml | Eau de Parfum | 6291107975054 |
| Magnate Premier | 100 ml | Eau de Parfum | 6291107975061 |
| Musk Al Sabah | 100 ml | Eau de Parfum | 6291107977027 |
| Oud Al Sabah | 100 ml | Eau de Parfum | 6291107977034 |

## First-party evidence

- Cashmere Warm Oud: https://khadlaj-perfumes.com/products/cashmere-warm-oud-100-ml-edp-spray-for-men-women
- Cashmere Sunshine Musk: https://khadlaj-perfumes.com/products/cashmere-sunshine-musk100-ml-edp-spray-for-men-women
- Ghadeer Silver: https://khadlaj-perfumes.com/products/ghadeer-silver-100-ml-edp-spray-for-men-women-best-edp-perfume-dubai-uae
- Infini Absolute: https://khadlaj-perfumes.com/products/infini-absolute-edp-spray-100-ml
- Sensuous Night: https://khadlaj-perfumes.com/products/sensous-night-edp-spray-shop-online-best-price-in-dubai-uae
- Oud Pour Noble: https://khadlaj-perfumes.com/products/oud-pour-noble-spray-shop-online-best-price-in-dubai-uae
- Oud Pour Shaikh: https://kw.khadlaj-perfumes.com/products/oud-pour-shaikh-spray-shop-online-best-price-in-dubai-uae
- Oud Pour Rouge: https://khadlaj-perfumes.com/products/oud-pour-rouge-spray-shop-online-best-price-in-dubai-uae
- Rose Couture: https://khadlaj-perfumes.com/collections/perfumes-spray/products/rose-couture-edp-spray-shop-online-best-price-in-dubai-uae
- Musk Pour Narcis: https://kw.khadlaj-perfumes.com/products/musk-pour-narcis-spray-shop-online-best-price-in-dubai-uae
- Oud Pour Blueberry: https://khadlaj-perfumes.com/collections/oud-pour-series-collection-shop-for-captivating-niche-fragrances/products/oud-pour-blueberry-spray-shop-online-best-price-in-dubai-uae
- Magnate Noble: https://khadlaj-perfumes.com/products/magnate-noble-100ml-edp-spray
- Magnate Premier: https://khadlaj-perfumes.com/collections/new-launches-top-fragrances-to-shop-online/products/magnate-premier-100ml-edp-spray
- Musk Al Sabah: https://khadlaj-perfumes.com/products/musk-al-sabah-100-ml-edp-spray-buy-online-best-price-dubai-uae
- Oud Al Sabah: https://khadlaj-perfumes.com/products/oud-al-sabah-100-ml-edp-spray-dubai-uae-amber-oud-fragrance

Some official product pages expose a Shopify default-title option while naming the exact size in the product heading; the size is recorded only where the official product title explicitly states it. The regional Kuwait storefront is an official Khadlaj domain and was used for Oud Pour Shaikh and Musk Pour Narcis where it exposes the size and numeric SKU clearly.

## Catalog changes

- Reused the fifteen existing canonical product IDs.
- Upgraded product identity status and stored individual official product-page provenance.
- Added one explicit size/concentration variant for the twelve products without one; three existing variants were preserved unchanged.
- Added numeric GTINs only when provided by the official product page; no identifiers were inferred.
- Updated the existing `khadlaj_official_perfume_sprays_2026_11` family-registry rows.
- No product identities were duplicated and no existing variants were overwritten.

No price, stock, availability, shipping, or retailer-offer data was imported.

## Regression coverage

`backend.tests.test_khadlaj_official_spray_third_followup` verifies canonical IDs, provenance, variant uniqueness, attributes, GTIN handling, and family-registry alignment.
