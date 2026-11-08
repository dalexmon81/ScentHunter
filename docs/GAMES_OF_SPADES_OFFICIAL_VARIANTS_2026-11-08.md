# Games of Spades official catalog and variants — 8 November 2026

## Source and scope

The brand-owned store is Jo Milano Paris (`jomilanoparis.com`). Its official site presents Game of Spades as one of its fragrance lines. The current all-perfumes collection and individual product pages were used as primary evidence.

This PR:
- attaches individual official product pages to 27 existing identities plus Queen;
- adds three separate official identities that were present on the official store but missing from the canonical catalog;
- adds 45 size variants where the official product page explicitly states the size in ml;
- does not add prices, retailer offers, stock or availability.

## Three new canonical identities

| Canonical identity | Official page | Verified size(s) | Concentration |
|---|---|---:|---|
| Blue Sapphire | https://jomilanoparis.com/products/game-of-spades-blue-sapphire-parfum-spray-3-0-oz-90ml | 90 ml | Parfum |
| Emerald Extrait | https://jomilanoparis.com/products/game-of-spades-emerald-extrait | 90, 50, 10 ml | Extrait de Parfum |
| Rouge Extrait | https://jomilanoparis.com/products/game-of-spades-rouge-extrait | 100, 30, 10 ml | Extrait de Parfum |

These are separate canonical identities from Black Sapphire, Emerald and Rouge. The Extrait versions are not folded into their non-Extrait counterparts.

## Existing identities with official individual product pages

Individual Jo Milano Paris product pages are now attached to:
All In, Bid, Black Sapphire, Blind Bid, Bluff, Bonus, Boston, Diamond, Double Bonus, Emerald, Full House Refresh, Gold, High Roller, Jackpot, King, Queen, Moon, No Limit, Opal, Platinum, Rouge, Royale, Ruby, Topaz, Trick, Wildcard, Win and Yellow Sapphire.

The previous Queen record incorrectly pointed to the King product page; it now points to its own official Queen page.

## Verified variants

The 45 variants cover these 18 identities:

- All In — 10, 30, 50, 100 ml
- Black Sapphire — 10, 30, 90 ml
- Blind Bid — 100 ml
- Bonus — 10, 30, 100 ml
- Diamond — 10, 30, 100 ml
- Double Bonus — 10, 30, 100 ml
- Emerald — 30, 100 ml
- Gold — 10, 30, 90 ml
- Jackpot — 10, 30, 100 ml
- King — 10, 30, 100 ml
- No Limit — 100 ml
- Opal — 100 ml
- Queen — 10, 30, 100 ml
- Rouge — 30, 100 ml
- Royale — 30, 50, 100 ml
- Blue Sapphire — 90 ml
- Emerald Extrait — 10, 50, 90 ml
- Rouge Extrait — 10, 30, 100 ml

Concentration is stored only where the individual page explicitly identifies it. For the other products, size is recorded without inventing a concentration. Sizes shown only in fluid ounces are not converted into ml for this change.

## Open evidence questions retained

- **Ace** remains `source_listed_name`, not `source_verified_name`. Its previous source incorrectly pointed to the King page; it now points to the official collection, with the official discovery-set page retained as supporting context. The store's current individual-page results do not provide a clear standalone Ace page. It is not silently merged into Platinum.
- **Jack** appears in the family registry but is absent from the canonical catalog. No standalone official product page was found during this pass, so it is not added.
- Gift sets and coffrets remain excluded from canonical wearable-fragrance identities.

## Snapshot after change

- Games of Spades canonical identities: 32 (29 existing + 3 new)
- Games of Spades variants: 45
- Total canonical identities: 2,065
- Total variants: 365

## Regression protection

`backend/tests/test_games_of_spades_official_variants.py` checks official product URLs, the three new canonical identities, exact supported size variants, concentration where explicit, family-registry alignment, and global ID integrity.
