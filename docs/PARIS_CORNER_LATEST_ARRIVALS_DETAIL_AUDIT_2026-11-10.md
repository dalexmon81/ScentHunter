# Paris Corner latest-arrival detail audit — 10 November 2026

## Official storefront observation

The official Paris Corner homepage's latest-arrivals section displays Zariya, Green Bet, Heer and The Show Magnifique. The official product pages for all four show a 100 ml size. The same storefront also highlights Lueur d'Espoir Memories of Summer; its individual page confirms 100 ml.

Sources:
- Homepage: https://www.pariscornerperfumes.com/
- Zariya: https://www.pariscornerperfumes.com/products/zariya
- Green Bet: https://www.pariscornerperfumes.com/products/green-bet
- Heer: https://www.pariscornerperfumes.com/products/heer
- The Show Magnifique: https://www.pariscornerperfumes.com/products/the-show-magnifique
- Lueur d'Espoir Memories of Summer: https://www.pariscornerperfumes.com/products/lueur-d-espoir-memories-of-summer

## Catalog reconciliation

All five canonical identities already existed in the cumulative catalog and already had one 100 ml variant. No duplicate products or variants were created.

- Zariya's individual official product page explicitly describes it as a unisex Eau de Parfum. The canonical product and its existing 100 ml variant now carry `Eau de Parfum`.
- Green Bet, Heer and The Show Magnifique pages show the 100 ml size but do not explicitly state concentration in the retrieved product-page content. Their concentration remains unset.
- Lueur d'Espoir Memories of Summer page shows 100 ml but does not explicitly state concentration. Its concentration remains unset.

Existing canonical product IDs and variant IDs are preserved. The Paris Corner family-registry entries are now aligned with the 100 ml formats. Missing variant-level source URLs for Green Bet, Heer and The Show Magnifique have also been populated from their individual official product pages.

## Regression coverage

Added `backend.tests.test_paris_corner_latest_arrivals_detail_audit_2026_11_10` to the catalog seed validation workflow. It checks the five official page URLs, existing canonical IDs, 100 ml variants, registry mappings, and the rule that concentration is only set for Zariya where the product page states it.

## CI feedback and correction

The first exact-head run exposed missing family-registry formats for these five existing products, missing variant-level source URLs for Green Bet, Heer and The Show Magnifique, and one incorrect expected product-ID literal in the new test. The registry, variant provenance and test expectation were corrected in the follow-up commit.

## Safety

No unverified concentration, GTIN, SKU, price, stock, availability or retailer offer has been inferred or added.
