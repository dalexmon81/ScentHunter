# Games of Spades — Jo Milano Paris official-page and variant reconciliation — 8 November 2026

## Source and scope

The brand owner is Jo Milano Paris. Its current official store presents the Game of Spades line within a larger perfume catalog and separates individual fragrances from gift sets and coffrets.

Official catalog:
https://jomilanoparis.com/collections/all

This pass:
- attaches individual official pages to 28 existing Games of Spades identities (all except the unresolved legacy `Ace` record);
- adds the new `Blue Sapphire` identity, whose individual official page shows 90 ml and 30 ml;
- adds 49 variants only where the official product page explicitly supports both size and concentration;
- treats Emerald Extrait and Rouge Extrait as concentration/size variants of their existing Emerald and Rouge identities, not duplicate canonical fragrances.

## Official individual-page reconciliation

Existing canonical records now link to their matching official detail pages:
- All In — https://jomilanoparis.com/products/game-of-spades-all-in
- Bid — https://jomilanoparis.com/products/game-of-spades-bid
- Black Sapphire — https://jomilanoparis.com/products/game-of-spades-black-sapphire
- Blind Bid — https://jomilanoparis.com/products/game-of-spades-blind-bid
- Bluff — https://jomilanoparis.com/products/game-of-spades-bluff-3-4-oz-parfum-spray-unisex
- Bonus — https://jomilanoparis.com/products/game-of-spades-bonus
- Boston — https://jomilanoparis.com/products/game-of-spades-boston
- Diamond — https://jomilanoparis.com/products/game-of-spades-diamond
- Double Bonus — https://jomilanoparis.com/products/game-of-spades-double-bonus
- Emerald — https://jomilanoparis.com/products/game-of-spades-emerald
- Full House Refresh — https://jomilanoparis.com/products/game-of-spades-full-house-refresh-3-4-oz-parfum-spray-unisex
- Gold — https://jomilanoparis.com/products/game-of-spades-gold
- High Roller — https://jomilanoparis.com/products/game-of-spades-high-roller-3-4-oz-parfum-spray
- Jackpot — https://jomilanoparis.com/products/game-of-spades-jackpot
- King — https://jomilanoparis.com/products/game-of-spades-king
- Moon — https://jomilanoparis.com/products/game-of-spades-moon
- No Limit — https://jomilanoparis.com/products/game-of-spades-no-limit
- Opal — https://jomilanoparis.com/products/game-of-spades-opal
- Platinum — https://jomilanoparis.com/products/game-of-spades-platinum
- Queen — https://jomilanoparis.com/products/game-of-spades-queen
- Rouge — https://jomilanoparis.com/products/game-of-spades-rouge
- Royale — https://jomilanoparis.com/products/game-of-spades-royale
- Ruby — https://jomilanoparis.com/products/game-of-spades-ruby
- Topaz — https://jomilanoparis.com/products/game-of-spades-no-limit-copy
- Trick — https://jomilanoparis.com/products/game-of-spades-trick-3-4-oz-parfum-spray-unisex
- Wildcard — https://jomilanoparis.com/products/game-of-spades-wildcard
- Win — https://jomilanoparis.com/products/game-of-spades-win
- Yellow Sapphire — https://jomilanoparis.com/products/game-of-spades-sapphire

`Ace` remains `source_listed_name`. The official Platinum page contains a textual mention of Ace, but no separate current Ace product page was located. The existing Ace identity is preserved without adding variants or upgrading its confidence; its evidence URL points to the Platinum page solely for that mention. This is not treated as proof that Ace and Platinum are the same fragrance.

## New identity

- Blue Sapphire — https://jomilanoparis.com/products/game-of-spades-blue-sapphire-parfum-spray-3-0-oz-90ml
- Official page explicitly shows 90 ml and 30 ml, with Parfum Spray formulation.
- Added as one new canonical identity and two variants.

## Verified variants

All sizes below are the official page's listed size options, including options marked sold out. No live stock status is copied.

| Canonical identity | Concentration | Sizes (ml) |
|---|---|---|
| All In | Parfum | 10, 30, 50, 100 |
| Bid | Parfum | 100 |
| Black Sapphire | Parfum | 10, 30, 90 |
| Blind Bid | Parfum | 100 |
| Bluff | Extrait de Parfum | 100 |
| Boston | Parfum | 30, 100 |
| Diamond | Parfum | 10, 30, 100 |
| Double Bonus | Parfum | 10, 30, 100 |
| Emerald | Extrait de Parfum | 10, 50, 90 |
| Full House Refresh | Parfum | 100 |
| Gold | Parfum | 10, 30, 90 |
| High Roller | Parfum | 100 |
| Jackpot | Parfum | 10, 30, 100 |
| King | Parfum | 10, 30, 100 |
| Queen | Parfum | 100 |
| Rouge | Parfum | 30, 100 |
| Rouge | Extrait de Parfum | 10, 30, 100 |
| Ruby | Parfum | 100 |
| Trick | Parfum | 100 |
| Wildcard | Parfum | 30, 50, 100, 200 |
| Win | Parfum | 100 |
| Yellow Sapphire | Parfum | 30, 90 |
| Blue Sapphire | Parfum | 30, 90 |

Emerald Extrait and Rouge Extrait source pages:
- https://jomilanoparis.com/products/game-of-spades-emerald-extrait
- https://jomilanoparis.com/products/game-of-spades-rouge-extrait

## Catalog guardrails

- No new canonical identities are created for Emerald Extrait or Rouge Extrait; concentration is represented in the variant records.
- `Ace` is not merged into Platinum.
- No product is created for the registry-only `Jack` entry without an individual product page.
- Gift sets, coffrets, and miniature discovery bundles are not imported as fragrance identities.
- Products with incomplete page detail remain without speculative variants.
- No price, offer, stock, availability, shipping, or retailer data is copied.

## Snapshot after change

- Total canonical identities: 2,074
- Total variants: 428
- Games of Spades canonical identities: 30
- Games of Spades variants: 49

## Regression protection

`backend/tests/test_games_of_spades_official_page_variants.py` checks official page provenance, the unresolved Ace confidence boundary, all 49 size/concentration pairs, Extrait variant source pages, registry format alignment, unique variant IDs, and valid parent references.
