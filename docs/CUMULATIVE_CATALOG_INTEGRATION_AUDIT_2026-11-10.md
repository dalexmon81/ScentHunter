# Final cumulative catalog evidence audit — 10 November 2026

## Starting point

This branch starts from the latest observed head of PR #649, commit 8606897ce35aa16512423ca52dbafb37b77f2fb1. That snapshot already contains the cumulative official-brand work, including the latest Khadlaj follow-up variants. The integration does not rebuild or replace those catalog records.

The starting snapshot contained 2,208 canonical products, 980 variants and 34 family-registry records. Its product/variant IDs, normalized brand/name identities, variant tuples and GTINs were unique, with no orphan variants.

## Evidence-safe corrections

Only unsupported attributes and their corresponding variant records are removed:

- **Tahara Vanilla Musk:** keep the existing Gulf Orchid canonical product and official product-page name evidence. The visible page does not state size or concentration. Remove the 60 ml EDP claim, its variant, and the family-registry format. The URL slug alone is not accepted as product specification.
- **Vanilla Voyage:** keep the existing Maison Asrar canonical identity and official page attribution. The visible page does not state size or concentration. Remove the EDP concentration claim; no variant is created.
- **Marwa:** keep the existing Arabiyat Prestige canonical ID as a name-only record. The previously cited individual product URL is not currently accessible; the official collection instead exposes “Arabiyat Marwa Extrait 60 ml”, which does not substantiate the claimed Arabiyat Prestige 100 ml EDP variant. Remove the 100 ml EDP variant and format, and downgrade the identity status to source-listed name.

All other records from the latest #649 head are preserved, including the newest Khadlaj official variants, the verified Gulf Orchid and Maison Asrar variants, the Velixir variants, Arabiyat Prestige variants and the Armaf Intenso Fuego 105 ml variant.

## Final snapshot validation

- 2,208 canonical products.
- 978 variants.
- 34 family-registry records.
- Zero duplicate product IDs.
- Zero duplicate variant IDs.
- Zero duplicate normalized brand/name identities.
- Zero duplicate product/size/concentration tuples.
- Zero duplicate GTINs.
- Zero orphan variants.
- Zero variants whose size is absent from the parent product's declared formats.
- No price, currency, availability, stock, retailer or offer fields imported into the canonical catalog.

These figures describe this branch's snapshot and must be confirmed by CI on the exact PR head.
