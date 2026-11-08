# Khadlaj La Fede collection reconciliation — 2026-11-08

## Official collection comparison

The official Khadlaj store currently shows 35 products in the parent
`LA FEDE` collection. The full parent collection was inspected across all
three storefront pages, not just the first 12 visible products:
- https://khadlaj-perfumes.myshopify.com/collections/la-fede
- https://khadlaj-perfumes.myshopify.com/collections/la-fede?page=2
- https://khadlaj-perfumes.myshopify.com/collections/la-fede?page=3

The separate official "New Launch La Fede Eau de Parfum" collection currently
shows 24 products:
- https://khadlaj-perfumes.com/collections/new-launch-la-fede-eau-de-parfum-collection-by-khadlaj-perfumes
- https://khadlaj-perfumes.com/collections/new-launch-la-fede-eau-de-parfum-collection-by-khadlaj-perfumes?page=2

The parent collection and new-launch collection overlap. Intoxicate Mystique
is separately verified on the official new-launch collection/product page,
even though it is not in the 35-item parent collection listing. Therefore,
the branch's 36 La Fede identities are reconciled as 35 parent-collection
products plus this additional official new-launch identity; no row was
deleted simply because it was absent from the parent collection.

Official product detail pages used for the previously under-sourced Celebrity
entries and Intoxicate Mystique:
- Celebrity Crush:
  https://khadlaj-perfumes.myshopify.com/collections/la-fede/products/la-fede-celebrity-crush-100ml-eau-de-parfum
- Celebrity Fame:
  https://khadlaj-perfumes.myshopify.com/collections/la-fede/products/la-fede-celebrity-fame-100ml-eau-de-parfum
- Intoxicate Mystique:
  https://khadlaj-perfumes.com/collections/new-launch-la-fede-eau-de-parfum-collection-by-khadlaj-perfumes/products/la-fede-intoxicate-blue-elixir-100-ml-eau-de-parfume-spray-for-men-copy

## Catalog changes

1. Created a dedicated `khadlaj_la_fede` family with 36 canonical products.
2. Moved all 36 La Fede identities from the general Khadlaj catalog and
   perfume-spray families into the dedicated family, preserving canonical
   product IDs.
3. Preserved Uno Lusso, Uno Intimo and Uno Durable in the general Khadlaj
   family. They are Uno Range products, not La Fede collection entries; their
   La Fede aliases remain search aliases only.
4. Upgraded the 36 La Fede product identities to `source_verified_name`
   using official collection/detail evidence.
5. Added explicit 100 ml Eau de Parfum variants for Celebrity Crush and
   Celebrity Fame. Their official product pages show 100 ML and their product
   titles specify Eau de Parfum.
6. Preserved Intoxicate Mystique as a separate canonical product with its
   existing 100 ml Extrait de Parfum variant. Its official page confirms the
   title, concentration, 100 ml size and SKU 6298043071598. The product URL
   slug is awkward and mentions Blue Elixir, but the page's actual product
   title and body identify Intoxicate Mystique; the catalog uses the page
   content, not the slug, as the product identity.

## Final Khadlaj family counts

| Family | Products |
|---|---:|
| khadlaj_catalog | 51 |
| khadlaj_official_perfume_sprays_2026_11 | 67 |
| khadlaj_shiyaaka | 8 |
| khadlaj_la_fede | 36 |
| **Total Khadlaj** | **162** |

The 35 parent-collection items and the additional official new-launch item
are distinct from gift sets and perfume oils. No gift sets, prices, stock,
retailer offers, shipping or GTIN records were added. Product SKU strings on
the official pages were not automatically promoted to GTIN registry entries.

## Tests and totals

Added six regression tests in `backend/tests/test_khadlaj_la_fede.py` for
collection reconciliation, registry parity, family separation, the two
100 ml EDP variants, Intoxicate Mystique's 100 ml Extrait identity and ID
uniqueness.

Whole branch totals after this update: 1,940 canonical products and 272
variants. This is a source-backed reconciliation of the current official
storefront snapshot, not a claim of exhaustive coverage of every historical
or regional La Fede release. CI must still run against the final PR head.
