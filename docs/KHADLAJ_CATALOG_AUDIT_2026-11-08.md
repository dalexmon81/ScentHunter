# Khadlaj catalog audit — 2026-11-08

## La Fede reconciliation

The official Khadlaj La Fede EDP collection reports 42 products. Its visible product cards, its filtered pages and the official La Fede family records identify the following 44 distinct products when the related Celebrity and Uno lines are included:
- 36 products visible in the main paginated collection.
- 3 Lavish products (Blush, Luna, Rouge) found in official Khadlaj product pages.
- 3 Uno products (Lusso, Sensuale, Durable) found in official Khadlaj's Uno Range; the product pages explicitly describe them as La Fede fragrances.
- 2 Celebrity products (Celebrity Crush and Celebrity Fame) already represented in the seed.
- Intoxicate Mystique is already represented and is an Extrait de Parfum, not EDP.

This update adds 41 new identities and 41 explicit 100 ml / 75 ml EDP variants to the catalog, preserving the three already represented La Fede identities. The official La Fede pages list 100 ml for most products; Statesman, First Lady, Kingsman and Miss Premiere are 75 ml.

The store's collection count and the visible paginated product cards are not fully consistent. This audit uses individual official product pages for all added rows, and the family registry's 44-item La Fede group as the canonical reconciliation target.

## Additional core spray display aliases

The main Perfume Sprays collection shows 101 products. The crawler exposed 96 product cards across the accessible pages; all 96 names resolve to existing catalog identities either directly or through the already recorded aliases. The remaining five entries in the collection's displayed count were not exposed by the final pagination response and remain a separate follow-up check.

## Validation

- 41 new La Fede / Uno product identities and 41 explicit EDP variants.
- 44 identities in the khadlaj_la_fede family registry after reconciliation.
- Celeste Fluer is retained as an alias for the official product title Celeste Fleur.
- No perfume oils, bakhoor, room fragrance or gift sets are added to the perfume catalog.
- Regression tests assert each new official product page, size and concentration.

## Sources

- Official Khadlaj Perfume Sprays: https://khadlaj-perfumes.com/collections/perfumes-spray
- Official Khadlaj La Fede EDP collection: https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume
- Official Khadlaj Uno Range: https://khadlaj-perfumes.com/collections/uno-range
- Individual official product pages are recorded in backend/product_catalog.json.
- Fragrantica Khadlaj designer index: https://www.fragrantica.com/designers/Khadlaj.html

## Scope note

Fragrantica's count of 147 perfumes is a historical database count, not a current in-stock count. The current brand catalog includes multiple sub-lines. The remaining five unexposed perfume-spray records need one more source pass before declaring Khadlaj fully closed.
