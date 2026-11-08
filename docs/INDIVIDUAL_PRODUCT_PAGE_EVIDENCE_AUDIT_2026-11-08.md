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

- 27 individual product pages were reviewed across six brands.
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


## Second pass — Armaf individual product pages (8 November 2026)

Three additional Armaf catalog identities currently marked `source_listed_name` were opened from the brand's official US storefront and checked at product-detail level:

| Existing catalog identity | Official product page | Explicit evidence on product page | Safe conclusion |
|---|---|---|---|
| Club de Nuit Intenso Fuego | https://armaf.com/products/club-de-nuit-intenso-fuego | Exact product name; Eau de Parfum; men; 3.4 oz | Individual identity verified; record EDP and 3.4 oz only if the catalog's unit policy supports source-native ounces |
| Club de Nuit Elite | https://armaf.com/products/club-de-nuit-elite-1 | Exact product name; Eau de Parfum; unisex; 3.4 oz | Individual identity verified; EDP, unisex and 3.4 oz explicit |
| Club de Nuit Intense Overdose | https://armaf.com/products/club-de-nuit-intense-overdose | Exact product name; Extrait de Parfum; men; 3.6 oz | Individual identity verified; preserve Extrait as its own concentration, not as EDP |

These three pages are first-party product details, not merely collection cards. They provide explicit product identity, concentration and size. The source's ounce measurements are intentionally not converted here.

The official storefront also lists adjacent products and gift sets that contain sprays, shampoos or body products. Those must not be mistaken for independent fine-fragrance identities without checking their own product details.

## Updated coverage

- 17 individual product pages reviewed across six brands.
- The second pass adds three individually verified Armaf identities.
- The overall audit remains a sample, not a full audit of the 1,872 listing-level identities.
- No product was added or deleted, no identity status was changed, and no variant was created.
- Catalog JSON and production code remain unchanged.


## Third pass — Lattafa individual product pages (8 November 2026)

Four more existing Lattafa identities marked `source_listed_name` were checked against individual product pages on the official Lattafa storefront:

| Existing catalog identity | Official product page | Explicit evidence on product page | Safe conclusion |
|---|---|---|---|
| Sheikh Al Shuyukh Supreme | https://lattafa.com/product/sheikh-al-shuyukh-supreme/ | Exact name; 100 ml; fragrance type Men | Individual identity verified; page does not explicitly state concentration in the captured product information |
| Jouri | https://lattafa.com/product/jouri/ | Exact name; fragrance type Women; fragrance notes and product information | Individual identity verified; captured page does not establish size or concentration |
| Ana Abiyedh Passion | https://lattafa.com/product/ana-abiyedh-passion/ | Exact name; 60 ml; fragrance type Women; fragrance notes and product information | Individual identity verified; page does not explicitly state concentration in the captured product information |
| Ameerat Al Arab Sugar Crown | https://lattafa.com/product/ameerat-al-arab-sugar-crown/ | Exact name; 100 ml; fragrance type Women; fragrance notes | Individual identity verified; page does not explicitly state concentration in the captured product information |

The product pages establish the named identities and the explicitly shown sizes/gender classifications. They do not provide a basis to fill concentration, so no concentration was inferred from related Lattafa products or from the collection category.

## Updated coverage

- 21 individual product pages reviewed across six brands.
- This pass adds four individual Lattafa product pages.
- The audit remains a sample, not a full audit of the 1,872 listing-level identities.
- No product was added or deleted, no identity status was changed, and no variant was created.
- Catalog JSON and production code remain unchanged.


## Fourth pass — Maison Alhambra / Lattafa USA product pages (8 November 2026)

Six more existing Maison Alhambra identities marked `source_listed_name` were checked against individual product pages on the Maison Alhambra USA storefront. The pages identify the seller as Maison Alhambra USA and the footer carries the Lattafa-USA copyright. This is treated as a Lattafa USA brand storefront source, not as proof that every international market carries the same assortment.

| Existing catalog identity | Product-detail page | Explicit page evidence | Safe conclusion |
|---|---|---|---|
| Afro Leather | https://maisonalhambra-usa.com/products/maison-alhambra-afro-leather-eau-de-parfum-for-everyone | EDP in title; 80 ml; barcode 6291108736081; unisex | Individual identity, concentration, size and barcode verified |
| Alpine Homme Sport | https://maisonalhambra-usa.com/products/maison-alhambra-alpine-homme-sport-eau-de-parfum-for-men | EDP in title; 100 ml; barcode 6291108735879; men | Individual identity, concentration, size and barcode verified |
| Anarch | https://maisonalhambra-usa.com/products/maison-alhambra-anarch-eau-de-parfum-for-everyone | EDP in title; 100 ml; barcode 6291107459080; unisex | Individual identity, concentration, size and barcode verified |
| Anchor Black | https://maisonalhambra-usa.com/products/maison-alhambra-anchor-black-eau-de-parfum-for-men | EDP in title; 100 ml; barcode 6291108730058; men | Individual identity, concentration, size and barcode verified |
| Athena | https://maisonalhambra-usa.com/products/maison-alhambra-athena-eau-de-parfum-for-women | EDP in title; 100 ml; barcode 6290360599243; women | Individual identity, concentration, size and barcode verified |
| Aura D'eclat | https://maisonalhambra-usa.com/products/maison-alhambra-aura-declat-eau-de-parfum-for-women | EDP in title; 100 ml; barcode 6291107459103; women | Individual identity, concentration, size and barcode verified; preserve the catalog spelling/alias relationship for D'eclat rather than creating a second identity |

### Source-quality note

A separate search surfaced MaisonAlhambra.co, but its own pages disclose an Amazon affiliate relationship and editorial/guide function. It is **not** used as first-party evidence in this audit. The six product details above instead come from the Maison Alhambra USA storefront, whose product pages show barcodes, selected sizes, and a footer naming Lattafa-USA.com. The US storefront evidence should not be silently generalized to every regional market.

## Updated coverage

- 27 individual product pages reviewed across six brands.
- This pass adds six individually checked Maison Alhambra pages.
- The audit remains a sample, not a full audit of the 1,872 listing-level identities.
- No product was added or deleted, no identity status was changed, and no variant was created.
- Catalog JSON and production code remain unchanged.


## Fifth pass — barcode and catalog cross-check (8 November 2026)

The official product-page evidence was compared with the actual Maison Alhambra records in the PR #439 catalog snapshot (`backend/product_catalog.json`, blob `a0e787b370902eb69860250b233feebe466054e2`).

### Current catalog evidence coverage

- Maison Alhambra identities in this snapshot: 207.
- Identities with at least one GTIN recorded: 3.
- Identities with a `source_product_url`: 3.
- GTIN values found in those records: 3.
- Duplicate GTINs within Maison Alhambra: 0.

The three records already carrying matching individual product URLs and GTINs are Afro Leather (6291108736081), Anarch (6291107459080), and Athena (6290360599243). Their current `identity_status` values are nevertheless still `source_listed_name`, despite individual product-page evidence being recorded. This is a catalog provenance/status inconsistency worth correcting in a separate data-focused change after the evidence and status semantics are reviewed.

Three other individually reviewed products — Alpine Homme Sport, Anchor Black and Aura D'eclat — have first-party product-page evidence recorded in this audit but currently have no `source_product_url`, GTIN, size or concentration in their catalog records. Their official page values are documented above; they have deliberately not been inserted into the seed in this documentation-only PR.

### Negative finding: Amber & Leather is not enough to validate a perfume record

The Maison Alhambra USA page found for the query "Amber & Leather" is specifically a **perfumed deodorant spray**, 250 ml, barcode 6291108731925 — not an Eau de Parfum product page:
https://maisonalhambra-usa.com/products/maison-alhambra-amber-and-leather-perfumed-deodorant-spray-for-men

The catalog identity `Amber & Leather` must therefore not inherit this deodorant's barcode or size as a perfume variant. A separate perfume product page is still required. This is a useful example of why product-form classification must precede GTIN matching.

### Other Maison Alhambra identities searched in this pass

No reliable matching first-party product-detail page was established in this pass for Amberley Ombre Blue, Amberley Pur Oud, Amberly Amoroso, or Bright Peach. Their existing collection-level evidence remains unchanged. No fields were inferred from search snippets, related products or third-party listings.

## Updated coverage and status

- 27 individually reviewed product pages remain the confirmed positive-page count in this audit.
- This pass adds a structured catalog/GTIN consistency check and one explicit negative product-form finding; it does not add positive perfume product-page confirmations.
- No catalog record, identity status, variant, GTIN, price, availability or production code was modified.
- The PR remains documentation-only. A future data PR should separately promote only the identities whose evidence and status semantics are unambiguous, and include regression tests for duplicate GTINs and product-form collisions.
