# ARMAF detail-page verification — 2026-11-08

## Scope

This pass upgrades only ARMAF identities for which the official US brand site supplied a matching product-detail page. The official all-fragrances collection contains mixed formats (EDP, EDT, extrait, parfum, body mist/spray, deodorants, body care, and more); its headline item count is not treated as a perfume count.

Official source: https://armaf.com/collections/all-perfumes

## Verified identities

Six existing canonical identities now have individual official product-page evidence and explicit concentration:
- Club de Nuit Untold — Eau de Parfum
- Club de Nuit Intense Man Pure Parfum — Parfum
- Club de Nuit Sillage — Eau de Parfum
- Club de Nuit Woman — Eau de Parfum
- Club de Nuit Urban Man Elixir — Eau de Parfum
- Club de Nuit Iconic — Eau de Parfum

The source page for Club de Nuit Iconic is the official product page titled CLUB DE NUIT ICONIC, even though its product URL contains the legacy slug `blue-iconic-200ml`.

## Explicit sizes added

Where the product page explicitly provided size equivalents in millilitres, added size variants:
- Club de Nuit Untold: 200, 105, 30, 10 ml
- Club de Nuit Sillage: 105, 30, 10, 250 ml
- Club de Nuit Woman: 200, 105, 30, 250, 10 ml
- Club de Nuit Urban Man Elixir: 105, 30, 10, 250 ml
- Club de Nuit Iconic: 200, 105, 30, 10 ml

Club de Nuit Intense Man Pure Parfum page showed 5 Oz but did not state an exact ml conversion; no size variant was invented for it.

No prices, availability, retailer offers, stock, shipping, or GTINs were imported. No product identity was added from collection totals alone.

## Validation

Added `backend/tests/test_armaf_detail_evidence.py` and included it in the catalog validation workflow. Individual product-page evidence remains distinct from collection-listing evidence.
