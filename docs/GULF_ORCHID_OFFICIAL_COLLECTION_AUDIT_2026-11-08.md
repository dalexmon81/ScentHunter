# Gulf Orchid official collection audit — 2026-11-09

## Scope and official sources

The audit covers both paginated result sets of the official Gulf Orchid perfume collection:

- Page 1: https://shop-gulforchid.com/collections/gulf-orchid-perfume
- Page 2: https://shop-gulforchid.com/collections/gulf-orchid-perfume?page=2
- Official shop navigation and category taxonomy: https://shop-gulforchid.com/products
- Corporate portfolio taxonomy: https://gulforchid.com/portfolio/gulf-orchid/

The storefront separates Perfumes from Body Mist, Hair Mist, Deodorant, Room Spray, Reed Diffuser, Mukhammaria, Body Lotion and gift/bundle categories. Product names from the generic collection index are not enough to establish an individual perfume identity.

## Reconciliation result

The two paginated perfume collection pages contain 30 listings. Two are gift bundles (Sweet Edition and Flirt Edition), leaving 28 individual perfume listings. Two of those listings are smaller sizes of fragrances also listed in 100 ml, so the catalog represents them as two canonical identities with multiple variants.

The catalog now contains **26 canonical Gulf Orchid perfume identities**:

- Vanilla Addiction
- Mango Ice
- Cotton Candy Musk
- Tahara Vanilla Musk
- Sweet Heaven
- Pink Marshmallow
- Coco Blanco
- Exotic Oud
- Vanilla Latte
- Cookie Bite
- Sweet Like Candy
- Sweet Heaven Extreme
- Piña Colada Musk
- Angel Musk
- Naughty Vanilla
- Yacht Club
- Sweet Heaven Cherry
- Candy Bite
- Sweet Cherry Kiss
- Creamy Pistachio
- Marshmallow
- Sweet Heaven Ice
- Crème Caramel
- Pomegranate Musk
- Mysterious Tahara Musk
- Toffee Musk

The following are not treated as Gulf Orchid canonical perfumes:
- Collection labels without an individually evidenced perfume page: Al Qasr, Asala, Hamsat, Hikma, Jawhara, Jewel, Riwaya and Turath.
- Gift bundles: Sweet Edition and Flirt Edition.
- Vanilla Aura and Vanilla Voyage, which are listed as Maison Asrar rather than Gulf Orchid and remain attributed to Maison Asrar.

## Variants and evidence

Only sizes explicitly shown on official individual product pages are recorded. Sweet Heaven and Sweet Heaven Extreme each have 20 ml and 100 ml EDP variants. Sweet Heaven Cherry has a 20 ml EDP variant. Angel Musk, Pomegranate Musk, Mysterious Tahara Musk, Toffee Musk and Piña Colada Musk have 60 ml EDP variants. The other size-verified products have 100 ml EDP variants.

Cotton Candy Musk and Tahara Vanilla Musk remain without size variants because the parsed official detail pages did not expose a reliable size label during this audit. Every recorded variant carries its official product-page evidence URL.

No prices, stock states, availability claims or retailer offers were imported. No size or concentration was inferred from a collection selector, URL slug alone, or product-name suffix.

## Validation

The dedicated regression suite verifies the 26-name canonical set, official product-page provenance, explicit size variants, absence of invented variants, exclusion of collection-only labels and bundles, correct Maison Asrar attribution, and consistency with the family registry.
