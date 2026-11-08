# Canonical catalog recovery and reconciliation — 2026-11-08

## Recovery
The previous PR head accidentally contained an empty `backend/product_catalog.json`.
The canonical seed was restored from the known-good base branch `catalog/brand-expansion-2026-11` (blob `b4cbbab6cb31c8d209ccd0802909cf88d91b74a1`) before applying only candidates missing by normalized brand + fragrance name.

## Resulting seed
- Canonical fragrance identities: **1,698**
- Explicit variant rows: **141**
- Brand labels represented: **22**
- Duplicate product IDs: **0**
- Duplicate brand + canonical-name pairs: **0**
- Duplicate variant IDs: **0**
- Orphan variants: **0**

## Reconciled additions
Thirty net-new canonical identities were added from the dated source overlays:
- Lattafa: Queen of Arabia; Musamam White Intense
- Swiss Arabian: Incense 01
- Games of Spades: 25 identities, bringing the line to 29 named fragrances
- Arabiyat Prestige: Gelato Raspberry Ripple; Gelato Black Currant Lolly

Four Mykonos collaboration display names were not retained as duplicate identities. They were merged into aliases of the existing canonical identities (MyEgo, Empire x RRQ, Glitch, Invade). Their source-listed size/concentration evidence remains attached to the existing product/variant identities.

## Source and data-quality rules
- Official product detail pages are marked as source-verified names.
- Collection listings and specialist retailer listings remain source-listed names.
- Size and concentration are added only where the source overlay explicitly records them.
- No prices, stock, shipping costs, retailer offers, or availability were created.
- Games of Spades remains a collection/line; manufacturer attribution is Jo Milano Paris, not a new manufacturer brand.

## Validation
A structural validation pass confirmed unique product and variant IDs, no duplicate brand/name identities, no orphan variants, the expected 29 Games of Spades names, and the four Mykonos collaboration aliases.
A regression test was added at `backend/tests/test_catalog_seed_recovery.py`. The GitHub Actions run still needs to complete before this recovery is considered CI-verified.
