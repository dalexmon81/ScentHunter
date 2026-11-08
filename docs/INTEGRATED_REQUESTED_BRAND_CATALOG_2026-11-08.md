# Integrated requested-brand catalog checkpoint — 2026-11-08

## Integrated snapshot
- Canonical product identities: 1,974
- Explicit variants: 212
- Arabiyat Prestige: 118 identities; 20 source-verified product-detail updates; 20 explicit variants
- Assaf: 140 listed identities (independent range index; not all individually product-detail verified)
- Khadlaj: 116 identities
- Paris Corner: 245 identities

## Integration
- Retained the newer catalog snapshot from the Khadlaj / Paris Corner harvest branch.
- Applied 20 Arabiyat Prestige product-detail evidence updates from the follow-up branch, merging aliases without duplicating canonical identities.
- Added 20 explicit size/concentration variants from recorded retailer product pages.
- Synchronized the existing Arabiyat Prestige family registry.
- Preserved the Assaf harvest already present in the parent branch.

## Quality and limits
- This checkpoint does not claim complete worldwide SKU coverage.
- Source-listed identities remain distinct from individually product-detail-verified identities.
- No prices, offers, stock, shipping, GTINs, or retailer availability were invented or imported.
- Al Wataniah remains a priority: the official all-products page currently shows 103 entries. The official site separately exposes 28 body-mist products and 9 air-freshener products; those categories must not be imported as perfume identities. The Classic, Eternal, Munchies and Niche collections also overlap, so their counts must not be summed as unique perfumes.
- CI must pass on this exact branch head before validation is considered complete.

## Safety
- Draft integration branch only; no merge to main or production.
- PR #424 remains separate and untouched.


## Al Wataniah source check (2026-11-08)
- Official all-products page: https://www.alwataniah.com/collections/all-products (103 entries at check time).
- Official Classic collection: https://www.alwataniah.com/collections/classic (47 entries; page 2 also exposes a separate 45-item listing view).
- Official Eternal collection: https://www.alwataniah.com/collections/eternal (22 entries).
- Official Munchies collection: https://www.alwataniah.com/collections/munchies (8 entries).
- Official Niche collection: https://www.alwataniah.com/collections/niche (9 entries).
- Official Body Mist collection: https://www.alwataniah.com/collections/body-mist (28 entries; exclude from perfume identities).
- Official Air Freshener collection: https://www.alwataniah.com/collections/air-freshener (9 entries; exclude from perfume identities).
- These category counts overlap and are not additive. The current seed count of 10 Al Wataniah identities is incomplete; no additional names were bulk-imported from mixed collection totals.
