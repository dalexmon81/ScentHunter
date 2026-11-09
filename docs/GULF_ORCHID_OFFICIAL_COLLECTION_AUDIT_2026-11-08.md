# Gulf Orchid official store audit — 2026-11-09

## Official sources and scope

This pass reconciles Gulf Orchid product detail pages from the official store:

- Perfume-filtered collection page 1: https://shop-gulforchid.com/collections/gulf-orchid-perfume
- Perfume-filtered collection page 2: https://shop-gulforchid.com/collections/gulf-orchid-perfume?page=2
- Gulf Orchid brand collection pages 1–5: https://shop-gulforchid.com/collections/gulf-orchid and the corresponding `?page=2` through `?page=5` pages
- Official shop category navigation: https://shop-gulforchid.com/products
- Corporate portfolio taxonomy: https://gulforchid.com/portfolio/gulf-orchid/

The official store separates Perfumes from Body Mist, Hair Mist, Deodorant, Room Spray, Reed Diffuser, Mukhammaria, Body Lotion, and gifting/bundle categories. Only product detail pages explicitly identifying an EDP were imported as perfume identities. Body mists, oils that are not EDPs, and bundles were not converted into EDP products.

## Catalog result

The catalog now contains **75 Gulf Orchid canonical EDP identities** with individual official product-page URLs. This includes the original 26 identities from the filtered perfume collections and 44 additional EDP identities discovered on the broader Gulf Orchid brand collection pages.

A follow-up source-discovery pass also verified five additional Gulf Orchid EDPs from individual product pages: Amour, Belle, Chic, Cloud 9 and Phantom. The storefront's current homepage also exposes other launches attributed to Maison Asrar; those were deliberately not added to Gulf Orchid.

The additional verified names include Al Qasr, Al Qasr Dahab, Mango Heaven, Heavenly Lychee, Mawj, Pistachio Musk, Dark Chocolate, Rare Rose, Coffee Note, Nobilty, Baklava Bite, El Capitan Legacy, El Capitan Extreme, El Capitan Elixir, El Capitan, Sweet Heaven Tobacco, Ruby Fizz, Mangotini, Mojito Obsession, Old Fashioned, Tahiti Colada, Vanilla on the Beach, Pacific, Shisha, Melody, Evening Dance, Mood for Oud, Love Me Now, Toxic Love, Arabian Nights, Love & Beyond, Naseem, Omsiah, Riwaya Chapter I, Riwaya Chapter II, Riwaya, Romantic For Him, Romantic For Her, Shiekh Aloud Navy, Marine, Angham, Flame, Almalek and Bali.

## Canonical identity and variants

- Sweet Heaven: 20 ml and 100 ml EDP variants.
- Sweet Heaven Extreme: 20 ml and 100 ml EDP variants.
- Sweet Heaven Ice: 20 ml and 100 ml EDP variants.
- Sweet Heaven Cherry: 20 ml and 100 ml EDP variants.
- Sweet Heaven Tobacco: 20 ml and 100 ml EDP variants.
- Other explicit size-specific products use the size printed on their individual detail page (including 60 ml, 100 ml and 110 ml formats).
- Arabian Nights is retained as an EDP identity without a size variant because the official detail page did not expose a reliable size.
- Cotton Candy Musk and Tahara Vanilla Musk remain without size variants for the same evidence-quality reason.

No price, stock state, availability claim, retailer offer or GTIN was imported. No size was inferred from a URL slug, collection selector or product-name suffix.

## Exclusions and attribution

- Gift bundles such as Sweet Edition and Flirt Edition are not canonical perfume identities.
- Body Mist listings (including Musk Tahara body mists) are excluded from the EDP catalog.
- Collection-only labels without an individual official perfume detail page remain excluded: Asala, Hamsat, Hikma, Jawhara, Jewel and Turath.
- Vanilla Aura and Vanilla Voyage remain attributed to Maison Asrar, not Gulf Orchid.
- Al Qasr and Riwaya were initially treated as collection-only labels, but were reinstated after individual official EDP product pages were found.

## Completeness limitation

The first five pages of the broader Gulf Orchid brand collection were inspected. Page 5 still displays a “Load More” control, and pages 6–8 could not be retrieved reliably. Follow-up searches of individual official product pages added five further verified EDPs. Therefore 75 is a verified minimum for the audited snapshot, not a claim that every historical or currently listed Gulf Orchid perfume has been exhausted.

## Validation

The dedicated regression suite checks the 75-name canonical set, official product-page provenance, explicit variants, no invented sizes, category exclusions, Maison Asrar attribution, and family-registry consistency.
