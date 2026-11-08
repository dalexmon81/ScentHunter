# Individual product-page evidence audit — first sample (8 November 2026)

## Scope and decision

This is a documentation-only evidence pass against the requested-brand catalog seed in PR #439. It checks a small, representative sample of records currently marked `source_listed_name` against first-party product-detail pages.

**No catalog JSON, product identity, variant, concentration, size field, price, stock, API, or production code was changed in this pass.** The purpose is to record what the individual pages actually prove before promoting records or creating variants in a later, separately reviewed data change.

## Evidence reviewed

| Brand | Existing catalog identity | First-party product page | Explicit evidence visible | Safe conclusion |
|---|---|---|---|---|
| Maison Alhambra | Jean Lowe Immortal | https://maisonalhambra-usa.com/products/maison-alhambra-jean-lowe-immortal-eau-de-parfum-for-men | Product name, Eau de Parfum, 100 ml, barcode 6291108735541 | Individual product identity verified; page explicitly states EDP and 100 ml |
| Maison Alhambra | Kismet | https://maisonalhambra-usa.com/products/maison-alhambra-kismet-eau-de-parfum-for-women | Kismet for Women, Eau de Parfum, 100 ml, barcode 6291107459264 | The page verifies the women’s product; it does not prove that a generic Kismet identity should absorb the separate Kismet for Men record |
| Armaf | Club de Nuit Intense Man | https://armaf.com/products/club-de-nuit-intense-for-man | Product name, EDP, size selector with 1.0 / 6.8 / 8.45 oz; separate EDT and Parfum/Extrait product pages also exist | Individual identity verified; concentrations and sizes must remain separate variants/products, not be collapsed |
| Armaf | Odyssey Mandarin Sky | https://armaf.com/products/odyssey-mega-for-men | Product name, EDP, 6.8 / 3.4 / 2.02 / 0.34 oz size options | Individual identity verified; preserve the source's ounce units until a deliberate conversion policy is applied |
| Lattafa | Fahad | https://lattafa.com/product/lattafa-fahad-80-ml/ | Fahad, 80 ml, men, Eau de Parfum in product description | Individual identity verified; 80 ml and EDP are explicit |
| Lattafa | Khamrah Waha | https://lattafa.com/product/khamrah-waha/ | Khamrah Waha, 100 ml, unisex | Individual identity verified; page establishes name and size, but does not explicitly state concentration in the captured product text |
| Khadlaj | Island Dreams | https://khadlaj-perfumes.com/products/island-dreams-100-ml-extrait-de-parfum | Island Dreams, 100 ml, Extrait de Parfum, SKU 6291107979991 | Individual identity verified; name, size, concentration and SKU are explicit |
| Khadlaj | Hareem Al Sultan Gold | https://khadlaj-perfumes.com/products/hareem-al-sultan-gold-35ml | 35 ml concentrated, non-alcoholic perfume oil; SKU 6291107970875 | Product identity verified, but product form is concentrated perfume oil. Do not model it as an ordinary alcohol spray or merge it with spray variants |
| Al Wataniah | Kayaan Classic | https://www.alwataniah.com/products/kayaan-classic | Kayaan Classic product-detail page and fragrance description | Individual identity verified; captured page does not establish size or concentration |
| Al Wataniah | Kayaan Terra | https://www.alwataniah.com/products/kayaan-terra | Kayaan Terra product-detail page and fragrance description | Individual identity verified; captured page does not establish size or concentration |
| Assaf | Addict Blue | https://assaf.ae/products/addict-blue | Product-detail page, 125 ml, SKU ARDB-SF-125-0002, fragrance description | Individual identity verified; 125 ml explicit |
| Assaf | Alex Enable | https://assaf.ae/products/alex-enable | Product-detail page, 100 ml, SKU ALX-100-00900, men, fragrance description | Individual identity verified; 100 ml explicit |
| Assaf | Alexandra | https://assaf.ae/products/alexandra | Product-detail page, 100 ml, SKU ALXD-100-00100 | Individual identity verified; 100 ml explicit |
| Assaf | Arkle | https://assaf.ae/products/arkle | Product-detail page, 200 ml, SKU APK-200-09500, fragrance description | Individual identity verified; 200 ml explicit |

## Important catalog rules reinforced by this pass

1. A product-detail page is stronger evidence for a named identity than a collection listing. It does not automatically validate every size or concentration previously associated with that identity.
2. Preserve separate concentration families where the manufacturer exposes separate EDT, EDP, Parfum or Extrait products. Armaf Club de Nuit Intense Man is a concrete example: the official site exposes distinct concentration-specific pages.
3. Do not infer concentration from a product title or from a sibling variant. Khamrah Waha and both Al Wataniah examples are deliberately left without a newly asserted concentration in this audit.
4. Preserve product form. Khadlaj Hareem Al Sultan Gold is explicitly a concentrated, non-alcoholic perfume oil, not an ordinary alcohol-based spray.
5. Keep source-native units and identifiers. Do not convert ounce options into millilitres or invent GTIN/SKU values.
6. The Assaf storefront also sells watches, sunglasses and care products. Collection membership alone is not enough to classify every listing as a fragrance; the individual product page must be checked.

## Coverage and limitations

- 14 individual product pages were reviewed across six brands.
- These are sample confirmations, not a full audit of the 1,872 listing-level identities.
- No product was added or deleted, no identity status was changed, and no variant was created.
- This document does not claim that any brand's catalog is complete.
- The catalog seed remains unchanged in this PR. Any future data promotion should be a separate, narrowly scoped JSON change with tests for identity collisions, concentration separation, product form, and variant evidence.

## First-party references

All product-detail URLs in the evidence table are manufacturer/brand storefront pages:
- Maison Alhambra USA: https://maisonalhambra-usa.com/
- Armaf: https://armaf.com/
- Lattafa: https://lattafa.com/
- Khadlaj Perfumes: https://khadlaj-perfumes.com/
- Al Wataniah: https://www.alwataniah.com/
- Assaf: https://assaf.ae/
