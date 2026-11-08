# Mykonos, Gulf Orchid and Aromatix source review — 8 November 2026

## Scope and decision

This pass compared the requested-brand seed against accessible official/brand storefront collection pages. It is a source-reconciliation review, not a declaration of worldwide historical completeness.

**No catalog rows or variants are changed in this review.** Public collection evidence is useful for discovery, but candidates require individual product-page checks and exact reconciliation before promotion to `source_verified_name` or addition as canonical identities.

## Mykonos

Current seed snapshot: 72 canonical identities, all `source_listed_name`.

Sources:
- Official brand collections: https://officialmykonos.com/collections
- Official 100 ml collection: https://officialmykonos.com/collections/100ml-collection
- Official 50 ml collection: https://officialmykonos.com/collections/50ml-colection

The official collection index reports 26 items in the 100 ml collection and 37 items in the 50 ml collection. These collections overlap: collaboration and core fragrances may offer both sizes. Do not sum the two counts as unique fragrances.

The existing seed contains many names displayed by these official collections, including Utopia, Sparkling Rosé, Satin Blanc, On The Rocks, Moroccan Vanilla, Musk Aura, Invade, Xoxo Rosy, Verve, Vanilla Clouds, Stilettos, Senja and Reflection Elixir. Multi-size listings include Glitch, Empire, MyEgo, Sorrento, Silent Whisper, Royal Ispahan, Reflection, Penthouse and Monaco Royale.

A full pass of the official `/collections/all` pagination (4 pages, 54 listings) shows 53 named fragrance identities plus one generic `Travel Size 15ML` listing. All 53 named fragrances are already represented among the 72 Mykonos canonical identities in this seed snapshot. The generic travel-size listing is not a separate fragrance identity and should not be added as a product. The 50 ml / 100 ml collections overlap and are not additive counts.

The 19 seed identities not present in the current 53-name official all-products view should remain in the catalog as existing source-listed records for now; absence from the current live assortment does not prove that they are invalid or historically nonexistent. This pass therefore found no missing Mykonos canonical identity to add. Individual detail pages are still needed to promote listing-level records or correct any concentration/size claims. Do not infer concentration from a collection title or retailer text.

## Gulf Orchid

Current seed snapshot: 23 canonical identities, all `source_listed_name`.

Sources:
- Brand storefront collection index: https://shop-gulforchid.com/collections
- Brand storefront perfume collection: https://shop-gulforchid.com/collections/gulf-orchid-perfume
- Brand storefront homepage: https://shop-gulforchid.com/

The storefront separates Perfume from Body Mist, Hair Mist, Deodorant, Room Spray, Reed Diffuser and personal-care products. These categories are out of scope for the canonical perfume catalog unless an individual item is independently confirmed as a perfume.

The rendered Gulf Orchid perfume collection shows product listings including Vanilla Addiction, Mango Ice, Cotton Candy Musk, Tahara Vanilla Musk, Sweet Heaven 20ML, Pink Marshmallow, Coco Blanco, Sweet Edition (gift set), Exotic Oud, Flirt Edition (gift set), Vanilla Latte, Cookie Bite, Sweet Like Candy, Sweet Heaven Extreme 20ML and Piña Colada Musk. The page has a Load More control, so this rendered view is not proof of complete pagination.

The seed overlaps many of these names. The 20 ml labels are size leads only; verify individual pages before adding or altering variants. Exclude Sweet Edition and Flirt Edition as separate fragrance identities because their collection descriptions identify them as sets.

The homepage also shows names such as Belgravia, Cloud 9, Legacy, Vanguard, Regent and Majesty. Treat these as discovery leads only: homepage rendering alone does not establish product taxonomy, exact brand attribution, size or concentration. Verify individual product pages before adding them.

## Aromatix

Current seed snapshot: 12 canonical identities, all `source_listed_name`, currently sourced from a Notino brand/category listing.

Sources:
- Shop Aromatix: https://shoparomatix.com/
- Signature Aromatix Collection: https://shoparomatix.com/pages/aromatic-collection

Shop Aromatix is a multi-brand retailer. Its navigation distinguishes an Aromatix brand listing from Aromatix X French Avenue. The Signature Aromatix Collection page describes a ten-fragrance collaboration with French Avenue. The retailer also lists many unrelated designer and Middle Eastern brands.

Do not treat every product sold by Shop Aromatix as an Aromatix-branded perfume. The collaboration line and any separate Aromatix-branded products must be modeled only after individual product pages establish exact identity and brand attribution. Keep the existing 12 Notino-listed names at listing-level until matched to reliable individual product details or a clearly scoped official collection.

## Next verification steps

1. Reconcile the complete Mykonos 50 ml and 100 ml collections against the 72 existing identities; inspect individual pages for missing identities and mismatched size/concentration facts.
2. Paginate Gulf Orchid's perfume collection and open individual perfume pages. Exclude bundles, body products and home fragrance.
3. Resolve the Aromatix brand vs Aromatix X French Avenue distinction and inspect the ten-product collaboration at product-detail level.
4. Add only genuinely missing canonical identities or explicit variants supported by individual source pages. Preserve source URLs and evidence status.
5. Add regression tests for every promoted product and rerun catalog integrity, family-registry and requested-brand coverage tests.

No retailer prices, stock status or commercial offers are copied into the canonical seed by this review.
