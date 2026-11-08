# Bujairami catalogue audit — official harvest batch 1 — 2026-11-08

## Scope and source hierarchy

- Official Bujairami Australia store, Inspired Perfumes collection: https://bujairami.com.au/collections/inspired
- Individual official product pages linked from that collection.
- Independent EU retailer guide: https://bujairamiperfumes.eu/ (not the official brand website).

The official Inspired Perfumes collection currently reports 1,175 products. The independent EU guide reports 1,207 scent pages and says the brand's own catalogue listed 1,223 scent names on 8 November 2026. These are different source scopes and should not be treated as exact equivalent counts. The independent guide is useful for cross-checking names, but it is not an official master catalog.

ScentHunter's starting seed contains 142 Bujairami identities and only two explicit variants. It is therefore not complete against the official store's published collection size.

## First batch

The first official collection page exposes a series of product links. Nine names absent from the seed were checked against individual official product pages and added:

- Glorious
- Ripper
- Madness Extreme
- Woody Oud
- Shortcake
- Lavish
- The Hype
- Lavish Life
- Vanacco

Three official product pages explicitly state 100 ml: Ripper, Woody Oud and Lavish. Those receive a 100 ml variant row without an inferred concentration. The other six are added as source-verified identities only; no size or concentration is guessed. Lavish Life's product title explicitly identifies it as an Extrait de Parfum, but no size variant is inferred from the page.

## Result and remaining work

- Bujairami identities: 142 → 151.
- Bujairami explicit variants: 2 → 5.
- All nine new records have individual official product-page URLs.
- This is only batch 1. The official Inspired Perfumes collection has 1,175 products; a large portion of the range still needs to be reconciled and harvested in batches.
- A comparison of the first 239 names exposed in the independent EU guide found 161 names not represented in the starting 142-product seed. Some may be new, historical, regional, aliases or out of scope; they are not bulk-imported without official product evidence.
- Body Sprays and Originals are separate collections and must be reviewed separately. Do not mix body sprays into perfume identities.

## Validation limits

This PR adds nine directly verified products; it does not claim the Bujairami catalog is complete. Future batches should continue through the official Inspired Perfumes collection, then separately review Originals and Body Sprays, while using the independent guide and Fragrantica as secondary cross-checks.
