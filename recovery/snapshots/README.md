# ScentHunter recovery provenance — 2026-11-17

This file records exact source commits and blobs used by the isolated recovery candidate. The original source branches and PRs remain unchanged.

## Canonical product/variant seed
- Source PR: [#425](https://github.com/dalexmon81/ScentHunter/pull/425), draft/open.
- Source branch: `catalog/brand-expansion-2026-11`.
- Source commit: `54d84edabd927f5c6a60616e176adc02a81b3af6`.
- `backend/product_catalog.json` blob: `b4cbbab6cb31c8d209ccd0802909cf88d91b74a1`.
- `backend/family_registry.json` blob: `97e952effb069889667cf9fe9b66e5ece1b58d18`.
- `backend/scenthunter_next_engine/verified_gtin_variant_map.json` blob: `6a5b4cb6ac2917fe45f4e528c45a8f673de1d2ab`.

## Cumulative discovery-family harvest
- Source PR: [#639](https://github.com/dalexmon81/ScentHunter/pull/639), draft/open.
- Source branch: `catalog/arabiyat-prestige-new-launch-verification-2026-11-10`.
- Source commit: `2362eaa310e2e6a981978ab5a64501831170ce36`.
- `backend/family_registry.json` blob: `3ee094e336eee206d5b86ca682efba2b6d2dcb58`.
- This source contains 34 families and 2,386 product references before reconciliation.

## Verified family-format increments
- PR #638, head `985010abae19e19934c08e860d2e4cb61935d47e`, family registry blob `f14ee71c7c197707860434968a21daf6b93256c5`: adds verified 35/100 ml format hints for Velixir Comus, Ether, Orpheus and Panacea; also removes two repeated alias strings.
- PR #639, head `2362eaa310e2e6a981978ab5a64501831170ce36`, family registry blob `3ee094e336eee206d5b86ca682efba2b6d2dcb58`: adds 100 ml hints for Arabiyat Prestige Marwa, Aariz and Aariz L’Absolu, plus 110 ml for Asháa Oud Noir; also removes the same repeated alias strings.

## Current main safety exclusions
- Current main commit at the time of reconciliation: `defe49283754281c81f540fbdc3ef5588097c692`.
- `backend/family_registry.json` blob: `36b811dca50955bc5f630c19545b3fac1d46bfb5`.
- Main contains nine family records; its non-empty exclusion rules are retained in the candidate.

## Reconciled candidate
- The recovery branch merges the harvest, canonical seed and current-main safety exclusions.
- 34 families; 2,440 product references; 2,366 case/whitespace-normalized brand/name keys.
- All 1,668 canonical catalog products are represented; no family IDs are missing.
- Case/whitespace-only duplicate family entries are consolidated. Punctuation/diacritic collisions remain documented in `recovery/candidates/name-collision-audit.md`.
- Product and GTIN records are not merged based on name normalization alone.
