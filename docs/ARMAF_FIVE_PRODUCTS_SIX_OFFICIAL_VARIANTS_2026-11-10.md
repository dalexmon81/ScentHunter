# Armaf — five existing products, six official variants (10 November 2026)

| Canonical product | Size | Concentration |
|---|---:|---|
| Club de Nuit Intense Man Pure Parfum | 150 ml | Parfum |
| Club de Nuit Intense Man Pure Parfum | 200 ml | Parfum |
| Club de Nuit Bling | 75 ml | Eau de Parfum |
| Club de Nuit Lionheart Man | 100 ml | Eau de Parfum |
| Club de Nuit Lionheart Woman | 100 ml | Eau de Parfum |
| Club de Nuit Maleka | 105 ml | Eau de Parfum |

The Armaf EU product pages provide the explicit metric sizes. Existing Armaf.com product pages remain the primary evidence for canonical identity and concentration. Product IDs are reused; product_catalog.json and the Armaf family registry are synchronized.

## Source discrepancy retained transparently

The Armaf EU Pure Parfum page is titled “Pure Parfum” and lists 150 ml and 200 ml, but its descriptive body also contains an “Eau de Parfum” label. The existing Armaf.com product page explicitly identifies this canonical product as Parfum. The variants therefore retain the existing Parfum classification and the EU page is used for size evidence. This discrepancy is recorded rather than silently changing concentration.

## Exclusions

- Club de Nuit Precieux IV is not changed: Armaf.com currently labels the page Eau de Toilette, while Armaf EU labels it Extrait de Parfum at 55 ml. That concentration conflict needs a separate identity/variant decision.
- Dunescape Dubai and Odyssey Go Mango Tropical Collection are not merged into existing Dunescape / Odyssey Go Mango identities because the EU product names and concentrations differ.
- No GTIN, price, stock, availability, shipping or retailer-offer data is imported.

## Structural checks

- 2,208 products and 1,099 variants.
- Six new variants, no new canonical products.
- Zero duplicate product IDs, variant IDs, product/size/concentration tuples or GTINs.
- Zero orphan variants or commercial offer fields in canonical variants.
