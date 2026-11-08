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
- Al Wataniah remains a priority: the official all-products collection shows 108 mixed catalog items. These must be separated into perfume identities versus non-perfume formats before import.
- CI must pass on this exact branch head before validation is considered complete.

## Safety
- Draft integration branch only; no merge to main or production.
- PR #424 remains separate and untouched.
