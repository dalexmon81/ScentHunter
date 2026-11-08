# Khadlaj catalog and family-registry reconciliation — 2026-11-08

## Official source scope

The official Khadlaj collections index currently reports 308 items in "All Products".
It also exposes separate product-type collections, including perfume sprays,
concentrated perfume oils, bakhoor, air fresheners, home and ambiance, and gift
sets. Current displayed collection counts include 88 perfume sprays, 43
concentrated perfume oils, 29 bakhoor, 25 air fresheners, 55 home/ambiance and
21 gift sets. These are collection listing counts, not a disjoint inventory:
the same item may appear in best-seller, new-launch, gender, line and product
type collections. They must not be summed to infer unique fragrances.

Official references:
- https://khadlaj-perfumes.com/collections
- https://khadlaj-perfumes.com/collections/la-fede
- https://khadlaj-perfumes.com/collections/new-launch-la-fede-eau-de-parfum-collection-by-khadlaj-perfumes?page=1
- https://khadlaj-perfumes.com/collections/la-fede-best-sellers-edp-signature-scents
- https://khadlaj-perfumes.com/collections/concentrated-perfume-oils
- https://khadlaj-perfumes.com/collections/perfumes-spray

## Branch reconciliation

The branch already contained 162 Khadlaj canonical product identities. The
registry had only eight records, all Shiyaaka entries duplicated in the
Khadlaj top-level family. The family registry has now been reconciled against
the existing product catalog by exact family ID and canonical name:

| Catalog family ID | Canonical products |
|---|---:|
| khadlaj_catalog | 85 |
| khadlaj_official_perfume_sprays_2026_11 | 69 |
| khadlaj_shiyaaka | 8 |
| **Total** | **162** |

The Shiyaaka line remains a distinct family. The 69 products sourced from the
official perfume-spray collection remain grouped separately. Maya remains
classified by its official concentrated-perfume-oil collection and its 20 ml
format; it has not been recast as a spray. No new canonical identities or
unverified variants were fabricated in this registry-only reconciliation.

## Variant coverage and limits

The branch currently has 81 Khadlaj variant records for 162 canonical
products. The other 81 product identities do not yet have explicit size and
concentration data in their catalog records, so this pass intentionally does
not invent variants for them. The official La Fede storefront shows 35 items
in its main collection, while its new-launch and best-seller pages are
separate overlapping collections. The existing 37 La Fede identities therefore
need a name-by-name reconciliation; collection totals alone are not enough to
delete or add products.

A product page for Musk Pure Musk Blend confirms the existing 60 ml EDP
variant and SKU 6291107978154. The "65 ml" text in the URL slug is not the
product's selected size: the page body, size selector and additional
information all state 60 ml. The existing 60 ml variant was deliberately
preserved.

## Verification

Added six regression tests at
`backend/tests/test_khadlaj_catalog_parity.py` covering:
- catalog family IDs against registry family IDs;
- exact canonical-name parity for each family;
- unique product IDs and canonical names;
- preservation of the separate Shiyaaka line;
- the 69-entry official perfume-spray family;
- correct classification of Maya as a concentrated perfume oil.

Whole branch totals remain 1,940 canonical products and 270 variants.
This is registry reconciliation, not proof that every historical, regional or
currently listed Khadlaj fragrance has been imported. No retailer offers,
prices, stock or shipping data were added.
